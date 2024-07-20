import requests
import bs4
from datetime import datetime
import logging
import time
import shelve

# Note: currently using my forked version of requests_throttler which removes the extra log handler added 
# The original PyPI can be used but there will be doubled log entries and reduced formatting ability
# PR submitted: https://github.com/se7entyse7en/requests-throttler/pull/19 but my fork can be used until it's fixed:
# pip install git+https://github.com/DavidBowley/requests-throttler.git@remove_log_handlers
from requests_throttler import BaseThrottler

class Article():
    """ An Article object represents one individual BBC News article
        It can be used to scrape and parse a news article given any valid BBC news URL
        Only designed to work with '/news/...' URLs - does NOT work with Live or Video posts etc.
    """

    def __init__(self, url):
        self.url = url
        self.raw_HTML = ''
        self.soup = None
        # The first headline that we see (never changes)
        self.headline = ''
        # The first body that we see (never changes)
        self.body = ''
        # The first byline that we see (never changes)
        self.byline = []
        # The first article timestamps that we see (never changes)
        # Could be multiple timestamps even on the first scrape (original and updated dates) as the article could have existed a while already
        self.timestamp = []
        # DEBUG: Captures every headline/body/byline/timestamp seen per article scrape *REGARDLESS* of whether it has changed
        # [Not currently implemented]
        self.all_future_headlines = []
        self.all_future_bodies = []
        self.all_future_bylines = []
        self.all_future_timestamps = []
        # Keeps a record of all headline/body/byline/timestamp changes seen on future article scrapes
        # [Not currently implemented]
        self.headline_changes = []
        self.body_changes = []
        self.byline_changes = []
        self.timestamp_changes = []
        # Records a timestamp for every fetch_HTML() call, so if the article hasn't changed we still have a record that we checked
        self.timestamps_fetch = []
        # Will potentially be used as a link between the Article object in persistent storage and the mapping from ID dict key -> Article object and/or URL dict key -> ID
        # [Not currently implemented]
        self.id = None
        # Flag for if any errors have occurred during parsing
        self.parse_errors = False

    def __str__(self):
        """ This may change for now but I need to pick something... 
            Going for both URL and headline for now
        """
        return str(self.headline) + '\n' + str(self.url)

    def fetch_HTML(self):
        """ While currently used in some testing functions, it's likely this method won't actually be used in the final version
            All news article HTTP requests will be bulk-routed through requests_throttler
        """
        self.raw_HTML = request_HTML(self.url)

    def parse_all(self):
        self.soup = bs4.BeautifulSoup(self.raw_HTML, 'lxml')
        self.parse_headline()
        self.parse_body()
        self.parse_byline()
        self.parse_timestamp()

    def parse_headline(self):
        self.headline = self.soup.h1.string
        if self.headline is None:
            logger.error('Parse Error: URL: %s --> Headline', self.url)
            self.parse_errors = True
        else:
            self.headline = str(self.headline)
    
    def parse_body(self):
        text_block_divs = self.soup.find_all('div', attrs={'data-component': 'text-block'})
        if len(text_block_divs) == 0:
            logger.error('Parse Error: URL: %s --> Body --> <div data-component=\'text-block\'>', self.url)
            self.body = None
            self.parse_errors = True
            return
        for div in text_block_divs:
            paragraphs = div.find_all('p')
            if len(paragraphs) == 0:
                logger.error('Parse Error: URL: %s --> Body --> <div data-component=\'text-block\'> --> <p>', self.url)
                self.body = None
                self.parse_errors = True
                return
            for p in paragraphs:
                # Delete class attribute from each parent <p>
                del p['class']
                # Do the same for each descendant of each <p> that is a Tag object (e.g. <a href> and <b>)
                for tag in p.descendants:
                    if isinstance(tag, bs4.element.Tag):
                        del tag['class']
                # Each paragraph must be on a new line for future diff functions to work
                self.body += str(p) + '\n'
        # The final <p> has a pointless '\n' so we strip this out
        self.body = self.body.rstrip()

    def parse_byline(self):
        """ The data is too inconsistent to create a reliable mapping (e.g. Author, Job Title, etc.) as different authors don't all have the same types of data
            It is probably possible with some work, but as the main focus of the project is comparing article headlines/body this will be left as a list of strings for now 
        """
        byline_block_div = self.soup.find('div', attrs={'data-component': 'byline-block'})
        if byline_block_div is None:
            # There is no byline-block present (some articles don't have one)
            # Note that this means there is no parse error logging logic used here as there's no way to differentiate between a broken parse or just no byline present on the page
            self.byline = None
        else:
            for string in byline_block_div.strings:
                self.byline.append(str(string))

    def parse_timestamp(self):
        """ At the time of writing, each visible date was inside a <time> element with a datetime attribute that conforms to ISO 8601
            Although a max of 2 <time> elements have only ever been seen, for debugging purposes we will collect all of them to confirm this assumption
            self.timestamp will be a list of Datetime objects
        """
        time_tag = self.soup.find_all('time', attrs={'data-testid': 'timestamp'})
        if len(time_tag) == 0:
            logger.error('Parse Error: URL: %s --> Timestamp --> <time data-testid=\'timestamp\'>', self.url)
            self.timestamp = None
            self.parse_errors = True
            return
        for tag in time_tag:
            iso_datetime = tag['datetime']
            self.timestamp.append(datetime.fromisoformat(iso_datetime))

    def debug_print(self):
        """ Takes an article object and prints the Headline, Body, Byline, and Timestamp attributes for debugging purposes
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
        """ Calls logger.debug to output: URL, Parse Errors (Boolean), Headline, Body, Byline, Timestamp
        """
        logger.debug('\n***URL***\n' + str(self.url) + '\n\n***Parse Errors***\n' + str(self.parse_errors) + 
                     '\n\n***Headline***\n' + str(self.headline) + '\n\n***Body***\n' + str(self.body) + 
                     '\n\n***Byline***\n' + str(self.byline) + '\n\n***Timestamp***\n' + str(self.timestamp) + '\n\n')

    def store(self):
        """ Stores the Article object in persistent storage
            WORK IN PROGRESS 
            TO DO:  - Likely need to remove the soup from the article before shelving - working ok for me at the moment but lots of reports online of issues
                    and I don't really need to keep it - it can be re-souped from the raw_HTML for debugging purposes later on if needed
                     - Need to assign the ID to the article object before it gets shelved too
        """
        # First we need to work out what the latest ID is, so we can assign the right ID to the Article and use it as the db key
        with shelve.open('articles_db') as db:
            # As we'll start at ID 1, if it doesn't exist then this is a new database
            if '1' not in db:
                logger.info('Added article object to ID 1 (database was empty)')
                db['1'] = self
            else:
                # Find the biggest ID used in the DB so far and prep the next key/ID up
                keys = list(db.keys())
                keys.sort(key=int)
                last_id = keys[-1]
                next_id = str(int(last_id) + 1)
                db[next_id] = self
                logger.info('Added article object to ID %s', next_id)


    def store_test(self):
        """ Trying to resolve issue with simply shelving one article 
        """
        with shelve.open('articles_db') as db:
            self.soup = None

            # logger.debug(self.__dict__)
            # DEBUG: add each attribute of the Article object to its own key and see what happens...
            attr_dict = self.__dict__            

            for attr in attr_dict:
                print(attr)
                db[attr] = attr_dict[attr]
            # db['1'] = self


def testing_Article_class():
    url = 'https://www.bbc.co.uk/news/articles/cw00rgq24xvo'
    # url = 'https://www.bbc.co.uk/news/articles/c4ngk17zzkpo'
    # url = 'https://www.bbc.co.uk/news/articles/cq5xel42801o'
    # url ='https://www.bbc.co.uk/news/articles/cl4y8ljjexro'
    # BBC In-depth article
    # url = 'https://www.bbc.co.uk/news/articles/c0www3qvx2zo' 
    # Article that should fail parsing (mostly)
    # url = 'https://www.bbc.co.uk/news/live/cljy6yz1j6gt'
    # Article that should fully fail parsing
    # url = 'https://webaim.org/techniques/forms/controls'

    test_article = Article(url)
    test_article.fetch_HTML()
    test_article.parse_all()
    test_article.debug_log_print()

def debug_file_to_article_object(filename):
    """ Debugging function: turn an offline file into an article object for testing purposes instead of fetching a live URL
        Pulls the HTML into the self.rawHTML attribute
        URL is not used and set to 'DEBUG'
    """
    debug_article = Article('DEBUG: no URL as created from offline file')
    with open(filename, encoding='utf-8') as my_file:
        debug_article.raw_HTML = my_file.read()
    return debug_article

def request_HTML(url):
    response = requests.get(url)
    # For some reason Requests is auto-detecting the wrong encoding so we're getting Mojibakes everywhere
    # Hard-coding as utf-8 shouldn't cause issues unless BBC change it for random pages which is unlikely
    response.encoding = 'utf-8'
    return response.text

def get_news_urls(debug=None):
    """ Extracts all the news article URLs from the BBC Homepage
        Returns a list of URL strings
        debug = integer; flag to reduce the number returned for testing purposes
    """
    news_homepage = 'https://www.bbc.co.uk/news'
    soup = bs4.BeautifulSoup(request_HTML(news_homepage), 'lxml')
    news_urls = []
    for link in soup.find_all('a'):
        href = link.get('href')
        # href attribute exists on the <a> AND contains '/news/articles/' AND is not the '#comments' version of the link
        if href is not None and href.find('/news/articles/') != -1 and href.find('comments') == -1:
            news_urls.append('https://www.bbc.co.uk' + href)
    # Remove duplicate URLs
    news_urls = list(set(news_urls))
    if debug is None:
        return news_urls
    else:
        return news_urls[:debug]

def urls_to_parsed_articles(urls, delay):
    """ Takes a list of URLs and returns a list of Article objects 
        with raw_HTML attribute value fetched via the requests_throttler
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
        article.raw_HTML = response.text
        article.parse_all()
        res.append(article)

    return res

def get_latest_news():
    urls = get_news_urls(debug=5)
    # urls = ['https://www.bbc.co.uk/news/articles/cw00rgq24xvo', 'https://www.bbc.co.uk/news/articles/c4ngk17zzkpo']
    # urls = ['https://www.bbc.co.uk/news/articles/cw00rgq24xvo']
    # As get_news_urls() has just been called, there has already been a HTTP request within the last few milliseconds
    # It's possible the first request of the throttler will be sent too close to the homepage scrape request - so we delay to avoid this
    time.sleep(2)
    articles = urls_to_parsed_articles(urls, delay=2)
    return articles

def testing_print_latest_news():
    articles = get_latest_news()
    for article in articles:
        article.debug_log_print()

def testing_store_articles():
    articles = get_latest_news()
    for article in articles:
        article.store()
    """
    article = debug_file_to_article_object('test_file.html')
    article.parse_all()
    article.store_test()
    """


def debug_table(debug_attrs):
    """ Builds a data table inside a HTML file with all the information from the article objects we want to see
        Currently pulls from template files in /debug_table/ (which is not part of the Git repo) but only using it for debugging so far
        debug_attrs = list of strings; must only include known Article object attributes
    """
    with open('debug_table/top.html', encoding='utf-8') as f:
        template_start = f.read()
    with open('debug_table/bottom.html', encoding='utf-8') as f:
        template_end = f.read()
    data_table_start = ''
    start_indent = 4
    data_table_start += indent(start_indent) + '<table>\n' + indent(start_indent + 2) + '<caption>' + 'Debug Table' + '</caption>\n'
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
    with shelve.open('testing_db') as db:
        # db['testing'] = 'This is a test'
        temp = db['testing']
        print(temp)

def testing_build_dummy_db():
    with shelve.open('articles_db') as db:
        for i in range(10, 0, -1):
            db[str(i)] = None

def testing_print_db():
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
    # testing_Article_class()
    # testing_print_latest_news()
    # testing_print_db()
    # testing_build_dummy_db()
    
    # testing_store_articles()

    debug_table(debug_attrs = ['id', 'url', 'headline', 'parse_errors'])

    