"""
    
    ***News Updates Monitor***
    A prototype app that checks for changes made to news articles after they are published

"""

import logging
import time
from datetime import datetime
import shelve

import requests
import bs4
from requests_throttler import BaseThrottler
# Note: currently using my forked version of requests_throttler which removes the extra log handler
# added. The original PyPI can be used but there will be doubled log entries and reduced formatting
# ability.
# PR submitted: https://github.com/se7entyse7en/requests-throttler/pull/19 but my fork can be used
# until it's fixed:
# pip install git+https://github.com/DavidBowley/requests-throttler.git@remove_log_handlers


class Article():
    """ An Article object represents one individual BBC News article
        It can be used to scrape and parse a news article given any valid BBC news URL
        Only designed to work with '/news/...' URLs - does NOT work with Live or Video posts etc.
    """

    def __init__(self, url):
        self.url = url
        self.raw_html = ''
        self.soup = None
        # The first headline that we see (never changes)
        self.headline = ''
        # The first body that we see (never changes)
        self.body = ''
        # The first byline that we see (never changes)
        self.byline = []
        # The first article timestamps that we see (never changes)
        # Could be multiple timestamps even on the first scrape (original and updated dates) as the
        # article could have existed a while already
        self.timestamp = []
        # DEBUG: Captures every headline/body/byline/timestamp seen per article scrape *REGARDLESS*
        # of whether it has changed
        # [Not currently implemented]
        self.all_future_headlines = []
        self.all_future_bodies = []
        self.all_future_bylines = []
        self.all_future_timestamps = []
        # Keeps a record of all headline/body/byline/timestamp changes seen on future article
        # scrapes [Not currently implemented]
        self.headline_changes = []
        self.body_changes = []
        self.byline_changes = []
        self.timestamp_changes = []
        # Records a timestamp for every fetch_html() call, so if the article hasn't changed we
        # still have a record that we checked
        self.timestamps_fetch = []
        # Will potentially be used as a link between the Article object in persistent storage and
        # the mapping from ID dict key -> Article object and/or URL dict key -> ID
        # [Not currently implemented]
        self.id = None
        # Flag for if any errors have occurred during parsing
        self.parse_errors = False

    def __str__(self):
        """ This may change for now but I need to pick something... 
            Going for both URL and headline for now
        """
        return str(self.headline) + '\n' + str(self.url)

    def fetch_html(self):
        """ While currently used in some testing functions, it's likely this method won't actually
            be used in the final version
            All news article HTTP requests will be bulk-routed through requests_throttler
        """
        self.raw_html = request_html(self.url)

    def parse_all(self):
        """ Creates the soup and calls all the individual parse methods """
        self.soup = bs4.BeautifulSoup(self.raw_html, 'lxml')
        self.parse_headline()
        self.parse_body()
        self.parse_byline()
        self.parse_timestamp()

    def parse_headline(self):
        """ Parses the article headline and logs a parse error if it fails """
        self.headline = self.soup.h1.string
        if self.headline is None:
            # pylint: disable-next=possibly-used-before-assignment
            logger.error('Parse Error: URL: %s --> Headline', self.url)
            self.parse_errors = True
        else:
            self.headline = str(self.headline)

    def parse_body(self):
        """ Parses the article body text and logs a parse error if it fails """
        text_block_divs = self.soup.find_all('div', attrs={'data-component': 'text-block'})
        if len(text_block_divs) == 0:
            logger.error(
                'Parse Error: URL: %s --> Body --> <div data-component=\'text-block\'>', self.url
                )
            self.body = None
            self.parse_errors = True
            return
        for div in text_block_divs:
            paragraphs = div.find_all('p')
            if len(paragraphs) == 0:
                logger.error(
                    'Parse Error: URL: %s --> Body --> ' +
                    '<div data-component=\'text-block\'> --> <p>', self.url
                    )
                self.body = None
                self.parse_errors = True
                return
            for p in paragraphs:
                # Delete class attribute from each parent <p>
                del p['class']
                # Do the same for each descendant of each <p> that is a Tag object
                # (e.g. <a href> and <b>)
                for tag in p.descendants:
                    if isinstance(tag, bs4.element.Tag):
                        del tag['class']
                # Each paragraph must be on a new line for future diff functions to work
                self.body += str(p) + '\n'
        # The final <p> has a pointless '\n' so we strip this out
        self.body = self.body.rstrip()

    def parse_byline(self):
        """ The data is too inconsistent to create a reliable mapping (e.g. Author, Job Title, etc)
            as different authors don't all have the same types of data. It is probably possible
            with some work, but as the main focus of the project is comparing article
            headlines/body this will be left as a list of strings for now 
        """
        byline_block_div = self.soup.find('div', attrs={'data-component': 'byline-block'})
        if byline_block_div is None:
            # There is no byline-block present (some articles don't have one)
            # Note that this means there is no parse error logging logic used here as there's no
            # way to differentiate between a broken parse or just no byline present on the page
            self.byline = None
        else:
            for string in byline_block_div.strings:
                self.byline.append(str(string))

    def parse_timestamp(self):
        """ At the time of writing, each visible date was inside a <time> element with a datetime
            attribute that conforms to ISO 8601. Although a max of 2 <time> elements have only
            ever been seen, for debugging purposes we will collect all of them to confirm this
            assumption.
            self.timestamp will be a list of Datetime objects
        """
        time_tag = self.soup.find_all('time', attrs={'data-testid': 'timestamp'})
        if len(time_tag) == 0:
            logger.error(
                'Parse Error: URL: %s --> Timestamp --> <time data-testid=\'timestamp\'>', self.url
                )
            self.timestamp = None
            self.parse_errors = True
            return
        for tag in time_tag:
            iso_datetime = tag['datetime']
            self.timestamp.append(datetime.fromisoformat(iso_datetime))

    def debug_print(self):
        """ Takes an article object and prints the Headline, Body, Byline, and Timestamp attributes
            for debugging purposes
        """
        print('\n***URL***')
        print(self.url)
        print('\n***Headline***')
        print(self.headline)
        print('\n***Body***')
        print(self.body)
        print('\n***Byline***')
        print(self.byline)
        print('\n***Timestamp***')
        print(self.timestamp)

    def debug_log_print(self):
        """ Calls logger.debug to output:
            URL, Parse Errors (Boolean), Headline, Body, Byline, Timestamp
        """
        logger.debug(
            '\n***URL***\n%s' +
            '\n\n***Parse Errors***\n%s' +
            '\n\n***Headline***\n%s' +
            '\n\n***Body***\n%s' +
            '\n\n***Byline***\n%s' +
            '\n\n***Timestamp***\n%s' +
            '\n\n',
            self.url, self.parse_errors, self.headline, self.body, self.byline, self.timestamp
            )

    def store(self):
        """ Stores the Article object in persistent storage
            Only used to store _new_ articles at the moment
        """
        # Remvoing the soup before pickling as it can lead to maximum recursion depth errors
        # Can be re-souped from raw_html if needed
        self.soup = None
        with shelve.open('articles_db') as db:
            # As we'll start at ID 1, if it doesn't exist then this is a new database
            if '1' not in db:
                self.id = 1
            # Otherwise find the next ID available
            else:
                keys = list(db.keys())
                keys.sort(key=int)
                last_id = int(keys[-1])
                self.id = last_id + 1
            db[str(self.id)] = self
            logger.info('Added article object to ID %s', self.id)


def testing_article_class():
    """ Test function for the Article class instance methods """
    # url = 'https://www.bbc.co.uk/news/articles/cw00rgq24xvo'
    # url = 'https://www.bbc.co.uk/news/articles/c4ngk17zzkpo'
    # url = 'https://www.bbc.co.uk/news/articles/cq5xel42801o'
    # url ='https://www.bbc.co.uk/news/articles/cl4y8ljjexro'
    # BBC In-depth article
    # url = 'https://www.bbc.co.uk/news/articles/c0www3qvx2zo'
    # Article that should fail parsing (mostly)
    url = 'https://www.bbc.co.uk/news/live/cljy6yz1j6gt'
    # Article that should fully fail parsing
    # url = 'https://webaim.org/techniques/forms/controls'

    test_article = Article(url)
    test_article.fetch_html()
    test_article.parse_all()
    test_article.debug_log_print()

def debug_file_to_article_object(filename):
    """ Debugging function: turn an offline file into an article object for testing purposes
        instead of fetching a live URL
        Pulls the HTML into the self.raw_html attribute
        URL is not used and set to 'DEBUG'
    """
    debug_article = Article('DEBUG: no URL as created from offline file')
    with open(filename, encoding='utf-8') as my_file:
        debug_article.raw_html = my_file.read()
    return debug_article

def request_html(url):
    """ Helper function for using requests to get the HTML """
    response = requests.get(url)
    # For some reason Requests is auto-detecting the wrong encoding so we're getting Mojibakes
    # everywhere. Hard-coding as utf-8 shouldn't cause issues unless BBC change it for
    # random pages which is unlikely
    response.encoding = 'utf-8'
    return response.text

def get_news_urls(debug=None):
    """ Extracts all the news article URLs from the BBC Homepage
        Returns a list of URL strings
        debug = integer; flag to reduce the number returned for testing purposes
    """
    news_homepage = 'https://www.bbc.co.uk/news'
    soup = bs4.BeautifulSoup(request_html(news_homepage), 'lxml')
    news_urls = []
    for link in soup.find_all('a'):
        href = link.get('href')
        # href attribute exists on the <a> AND contains '/news/articles/'
        # AND is not the '#comments' version of the link
        if href is not None and href.find('/news/articles/') != -1 and href.find('comments') == -1:
            news_urls.append('https://www.bbc.co.uk' + href)
    # Remove duplicate URLs
    news_urls = list(set(news_urls))
    if debug is not None:
        return news_urls[:debug]
    return news_urls

def urls_to_parsed_articles(urls, delay):
    """ Takes a list of URLs and returns a list of Article objects 
        with raw_html attribute value fetched via the requests_throttler
        The returned objects should be ready to parse via self.parse_all()
        urls = list of strings
        delay = float; seconds to use for requests throttling
    """
    # List of request objects to send to the throttler
    reqs = []
    for url in urls:
        request = requests.Request(method='GET', url=url)
        reqs.append(request)

    # Throttler queues all the requests and processes them slowly
    # This step can take a while depending on the delay and number of URLs
    with BaseThrottler(name='base-throttler', delay=delay) as bt:
        throttled_requests = bt.multi_submit(reqs)
    responses = [tr.response for tr in throttled_requests]

    res = []
    for response in responses:
        response.encoding = 'utf-8'
        article = Article(response.url)
        article.raw_html = response.text
        article.parse_all()
        res.append(article)

    return res

def get_latest_news():
    """ Parses the latest news articles from the BBC news homepage
        Returns a list of article objects
    """
    # DEBUG: only 2 hard-coded URLs
    #urls = [
    #'https://www.bbc.co.uk/news/articles/cw00rgq24xvo',
    #'https://www.bbc.co.uk/news/articles/c4ngk17zzkpo'
    #]

    # DEBUG: only 1 hard-coded URL
    # urls = ['https://www.bbc.co.uk/news/articles/cw00rgq24xvo']

    urls = get_news_urls(debug=5)
    # As get_news_urls() has just been called, there has already been a HTTP request within the
    # last few milliseconds. It's possible the first request of the throttler will be sent too
    # close to the homepage scrape request - so we delay to avoid this
    time.sleep(2)
    articles = urls_to_parsed_articles(urls, delay=5)
    return articles

def testing_print_latest_news():
    """ Test function to debug_log print the latest news """
    articles = get_latest_news()
    for article in articles:
        article.debug_log_print()

def testing_store_articles():
    """ Test function to get the latest news and then store in persistent storage """
    articles = get_latest_news()
    for article in articles:
        article.store()

def debug_table(debug_attrs):
    """ Builds a data table inside a HTML file with all the information from the article objects we
        want to see.
        Currently pulls from template files in /debug_table/ (which is not part of the Git repo)
        but only using it for debugging so far.
        debug_attrs = list of strings; must only include known Article object attributes
    """
    with open('debug_table/top.html', encoding='utf-8') as f:
        template_start = f.read()
    with open('debug_table/bottom.html', encoding='utf-8') as f:
        template_end = f.read()
    data_table_start = ''
    start_indent = 4
    data_table_start += (
        indent(start_indent) + '<table>\n' +
        indent(start_indent + 2) + '<caption>' + 'Debug Table' + '</caption>\n'
        )
    data_table_start += indent(start_indent+2) + '<tr>\n'
    for th in debug_attrs:
        data_table_start += indent(start_indent+4) + '<th>' + th + '</th>\n'
    data_table_start += indent(start_indent+2) + '</tr>'
    # Overwrite existing HTML file if it exists
    with open('debug_table/debug_table.html', 'w', encoding='utf-8') as f:
        f.write(template_start)
        f.write('\n\n' + data_table_start + '\n\n')
    # Start outputing the data rows
    with shelve.open('articles_db') as db:
        ids = list(db.keys())
        ids.sort(key=int)
        for _id in ids:
            article = db[_id]
            article_dict = article.__dict__
            data_row = ''
            data_row += indent(start_indent+2) + '<tr>\n'
            for attr in  debug_attrs:
                data_row += indent(start_indent+4) + '<td>' + str(article_dict[attr]) + '</td>\n'
            data_row += indent(start_indent+2) + '</tr>'
            # Append to existing HTML file
            with open('debug_table/debug_table.html', 'a', encoding='utf-8') as f:
                f.write(data_row + '\n\n')
        data_table_end = indent(start_indent) + '</table>'
        # End the table and finalise file template - append to existing HTML file
        with open('debug_table/debug_table.html', 'a', encoding='utf-8') as f:
            f.write(data_table_end + '\n\n')
            f.write(template_end)

def indent(spaces):
    """ Returns a string matching the number of spaces needed for the indent
        spaces = integer
    """
    return ' ' * spaces



def testing_shelves():
    """ Test function """
    with shelve.open('testing_db') as db:
        # db['testing'] = 'This is a test'
        temp = db['testing']
        print(temp)

def testing_build_dummy_db():
    """ Test function: builds a dummy database with IDs ready for testing """
    with shelve.open('articles_db') as db:
        for i in range(10, 0, -1):
            db[str(i)] = None

def testing_print_db():
    """ Test function: prints out the article objects from persistent storage """
    with shelve.open('articles_db') as db:
        keys = list(db.keys())
        keys.sort(key=int)
        for key in keys:
            print(key, db[key])



if __name__ == '__main__':

    # Create a logger
    logger = logging.getLogger()
    logger.setLevel(logging.DEBUG)

    # Create a formatter to define the log format
    formatter = logging.Formatter('%(asctime)s - %(levelname)s: %(message)s')

    # Create a file handler to write logs to a file
    file_handler = logging.FileHandler('debug.log', encoding='utf-8')
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)

    # Create a stream handler to print logs to the console
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.DEBUG)
    console_handler.setFormatter(formatter)

    # Add the handlers to the logger
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

    # testing_get_latest_news()
    # testing_anchor_links()
    # testing_access_filtered_obj_attrs()
    # testing_article_class()
    # testing_print_latest_news()
    # testing_print_db()
    # testing_build_dummy_db()

    # testing_store_articles()

    debug_table(debug_attrs = ['id', 'url', 'headline', 'body', 'byline', 'timestamp'])
