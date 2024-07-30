"""
    
    ***News Updates Monitor***
    A prototype app that checks for changes made to news articles after they are published

"""

import pprint
import logging
import time
from datetime import datetime, timezone
import shelve
import sqlite3

import requests
from requests.adapters import HTTPAdapter
import bs4
from requests_throttler import BaseThrottler
# Note: currently using my forked version of requests_throttler which removes the extra log handler
# added. The original PyPI can be used but there will be doubled log entries and reduced formatting
# ability.
# PR submitted: https://github.com/se7entyse7en/requests-throttler/pull/19 but my fork can be used
# until it's fixed:
# pip install git+https://github.com/DavidBowley/requests-throttler.git@remove_log_handlers


class Article():
    """ An Article object represents a snapshot in time of one individual BBC News article
        It can be used to scrape and parse a news article given any valid BBC news URL
        Only designed to work with '/news/...' URLs - does NOT work with Live or Video posts etc.
    """

    def __init__(
        self,
        url,
        raw_html='',
        fetched_timestamp=None,
        soup=None,
        parsed=None
        ):
        if parsed is None:
            parsed = {
            'headline': '',
            'body': '',
            'byline': '',
            '_timestamp': '',
            'parse_errors': False
            }
        self.url = url
        self.raw_html = raw_html
        self.fetched_timestamp = fetched_timestamp
        self.soup = soup
        self.parsed = parsed

    def __str__(self):
        """ This may change for now but I need to pick something... 
            Going for both URL and headline for now
        """
        return str(self.parsed['headline']) + '\n' + str(self.url)

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
        self.parsed['headline'] = self.soup.h1.string
        if self.parsed['headline'] is None:
            # pylint: disable-next=possibly-used-before-assignment
            logger.error('Parse Error: URL: %s --> Headline', self.url)
            self.parsed['parse_errors'] = True
        else:
            self.parsed['headline'] = str(self.parsed['headline'])

    def parse_body(self):
        """ Parses the article body text and logs a parse error if it fails """
        text_block_divs = self.soup.find_all('div', attrs={'data-component': 'text-block'})
        if len(text_block_divs) == 0:
            logger.error(
                'Parse Error: URL: %s --> Body --> <div data-component=\'text-block\'>', self.url
                )
            self.parsed['body'] = None
            self.parsed['parse_errors'] = True
            return
        for div in text_block_divs:
            paragraphs = div.find_all('p')
            if len(paragraphs) == 0:
                logger.error(
                    'Parse Error: URL: %s --> Body --> ' +
                    '<div data-component=\'text-block\'> --> <p>', self.url
                    )
                self.parsed['body'] = None
                self.parsed['parse_errors'] = True
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
                self.parsed['body'] += str(p) + '\n'
        # The final <p> has a pointless '\n' so we strip this out
        self.parsed['body'] = self.parsed['body'].rstrip()

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
            self.parsed['byline'] = None
        else:
            byline = []
            for string in byline_block_div.strings:
                byline.append(str(string))
            self.parsed['byline'] = ', '.join(byline)

    def parse_timestamp(self):
        """ At the time of writing, each visible date was inside a <time> element with a datetime
            attribute that conforms to ISO 8601. Although a max of 2 <time> elements have only
            ever been seen, for debugging purposes we will collect all of them to confirm this
            assumption.
            self.parsed['_timestamp'] will be a list of Datetime objects
        """
        time_tag = self.soup.find_all('time', attrs={'data-testid': 'timestamp'})
        if len(time_tag) == 0:
            logger.error(
                'Parse Error: URL: %s --> Timestamp --> <time data-testid=\'timestamp\'>', self.url
                )
            self.parsed['_timestamp'] = None
            self.parsed['parse_errors'] = True
            return
        iso_datetime = []
        for tag in time_tag:
            iso_datetime.append(tag['datetime'])
        self.parsed['_timestamp'] = ', '.join(iso_datetime)

    def debug_print(self):
        """ Takes an article object and prints the Headline, Body, Byline, and Timestamp attributes
            for debugging purposes
        """
        print('\n***URL***')
        print(self.url)
        print('\n***Headline***')
        print(self.parsed['headline'])
        print('\n***Body***')
        print(self.parsed['body'])
        print('\n***Byline***')
        print(self.parsed['byline'])
        print('\n***Timestamp***')
        print(self.parsed['_timestamp'])

    def debug_log_print(self):
        """ Calls logger.debug to output:
            URL, Parse Errors (Boolean), Headline, Body, Byline, Timestamp
        """
        logger.debug(
            '\n***URL***\n%s' +
            '\n\n***Fetched Timestamp***\n%s' +
            '\n\n***Parse Errors***\n%s' +
            '\n\n***Headline***\n%s' +
            '\n\n***Body***\n%s' +
            '\n\n***Byline***\n%s' +
            '\n\n***Timestamp***\n%s' +
            '\n\n',
            self.url, self.fetched_timestamp, self.parsed['parse_errors'], self.parsed['headline'],
            self.parsed['body'], self.parsed['byline'], self.parsed['_timestamp']
            )

    def store(self):
        """ Stores the Article object in persistent storage
            Only used to store _new_ articles at the moment
            Stores as a singleton list because we'll be adding other article snapshots later
        """
        # Remvoing the soup before pickling as it can lead to maximum recursion depth errors
        # Can be re-souped from raw_html if needed
        self.soup = None
        # New storage process goes here
        logger.info('Added article object to ID %s', 'DEBUG NOTE: not sure we need this now')

    def store_existing(self):
        """ When storing an article object into an existing database entry
            (e.g. because we've found a changed article and want to add it in)...
            We can add to the existing list of article objects
            We can also use this to get specific article snapshots, e.g.
            e.g. db[key][0] would be the original article snapshot
            and db[key][-1] would be the last article snapshot recorded
        """

    def to_row_dict(self):
        """ Converts the Article object into a dictionary suitable for passing into the SQLite
            database as a new row. The parsed dicitonary is also flattened out.
        """
        article_dict = self.__dict__
        article_dict.update(article_dict['parsed'])
        del article_dict['parsed']
        del article_dict['soup']
        return article_dict



class TimeoutHTTPAdapter(HTTPAdapter):
    """ Allows requests.Session() to use a modifed .send() method that injects a default timeout
        value. It will not override any specific timeout keyword arguments set via the caller.
    """
    def __init__(self, *args, **kwargs):
        if "timeout" in kwargs:
            self.timeout = kwargs["timeout"]
            del kwargs["timeout"]
        super().__init__(*args, **kwargs)

    def send(self, request, **kwargs):
        # pylint: disable=arguments-differ
        # As far as I can tell, this is the most official non-offical way to get requests to
        # actually work with a default global timeout on requests.Session(). There seems to be
        # multiple reported issues online of **kwargs causing this to flag when using a subclass
        # so I think this is a false positive. It's specifically recommended on the requests
        # github here: https://github.com/psf/requests/issues/2011
        timeout = kwargs.get("timeout")
        if timeout is None and hasattr(self, 'timeout'):
            kwargs["timeout"] = self.timeout
        return super().send(request, **kwargs)


###
### Start of Testing / Debug functions
###

def testing_print_latest_news():
    """ Test function to debug_log print the latest news """
    articles = get_latest_news()
    for article in articles:
        article.debug_log_print()

def testing_exceptions():
    """ Test function to make sure Timeout, Connection and other exceptions
        are working via requests_throttler
    """
    urls = [
    'https://github.com/kennethreitz/requests/issues/1236',
    'https://www.github.com',
    'http://fjfklsfjksjdoijfkjsldf.com/',
    'https://www.yahoo.co.uk',
    ]
    articles = urls_to_parsed_articles(urls, delay=5)
    for article in articles:
        article.debug_log_print()

def testing_article_class():
    """ Test function for the Article class instance methods """
    # url = 'https://www.bbc.co.uk/news/articles/cw00rgq24xvo'
    # url = 'https://www.bbc.co.uk/news/articles/c4ngk17zzkpo'
    url = 'https://www.bbc.co.uk/news/articles/cq5xel42801o'
    # url ='https://www.bbc.co.uk/news/articles/cl4y8ljjexro'
    # BBC In-depth article
    # url = 'https://www.bbc.co.uk/news/articles/c0www3qvx2zo'
    # Article that should fail parsing (mostly)
    # url = 'https://www.bbc.co.uk/news/live/cljy6yz1j6gt'
    # Article that should fully fail parsing
    # url = 'https://webaim.org/techniques/forms/controls'

    test_article = Article(url)
    test_article.fetch_html()
    test_article.parse_all()
    test_article.debug_log_print()

def debug_file_to_article_object(url, filename):
    """ Debugging function: turn an offline file into an article object for testing purposes
        instead of fetching a live URL
        Pulls the HTML into the self.raw_html attribute
    """
    debug_article = Article(url)
    with open(filename, encoding='utf-8') as my_file:
        debug_article.raw_html = my_file.read()
    return debug_article

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
    with shelve.open('db/articles_db') as db:
        keys = list(db.keys())
        keys.sort(key=int)
        for key in keys:
            print(key, db[key])

def debug_table(attrs, parsed):
    """ Builds a data table inside a HTML file with all the information from the article objects we
        want to see.
        Currently pulls from template files in /debug_table/ (which is not part of the Git repo)
        but only using it for debugging so far.
        attrs = list of strings; must only include known Article object attributes (but NOT parsed)
        parsed = dictionary keys as per article.parsed[...] to specify specific parsed info
        The ID will always be output as the first column regardless of other details requested
    """
    # pylint: disable=too-many-locals
    # Agree with pylint that this function is too complex, however it's purely for internal
    # debugging and won't be in the final version in this form. If I do decide to reuse parts of
    # this (e.g. to make a dashboard) then I will definitely simplify it and remove some of the
    # variables.
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
    data_table_start += indent(start_indent+4) + '<th>' + 'ID' + '</th>\n'
    data_table_start += indent(start_indent+4) + '<th>' + 'Snapshot' + '</th>\n'
    for th in attrs:
        data_table_start += indent(start_indent+4) + '<th>' + th + '</th>\n'
    for th in parsed:
        data_table_start += indent(start_indent+4) + '<th>' + th + '</th>\n'
    data_table_start += indent(start_indent+2) + '</tr>'
    # Overwrite existing HTML file if it exists
    with open('debug_table/debug_table.html', 'w', encoding='utf-8') as f:
        f.write(template_start)
        f.write('\n\n' + data_table_start + '\n\n')
    # Start outputing the data rows
    with shelve.open('db/articles_db') as db:
        ids = list(db.keys())
        ids.sort(key=int)
        for _id in ids:
            article_list = db[_id]
            n = 0
            for article in article_list:
                article_dict = article.__dict__
                data_row = ''
                data_row += indent(start_indent+2) + '<tr>\n'
                data_row += indent(start_indent+4) + '<td>' + _id + '</td>\n'
                data_row += indent(start_indent+4) + '<td>' + str(n) + '</td>\n'
                for attr in  attrs:
                    data_row += (
                        indent(start_indent+4) + '<td>' + str(article_dict[attr]) + '</td>\n'
                        )
                for item in parsed:
                    data_row += (
                        indent(start_indent+4) + '<td>' + str(article.parsed[item]) + '</td>\n'
                        )
                data_row += indent(start_indent+2) + '</tr>'
                # Append to existing HTML file
                with open('debug_table/debug_table.html', 'a', encoding='utf-8') as f:
                    f.write(data_row + '\n\n')
                n += 1
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

def testing_article_comparison():
    """ Test function """
    article1 = debug_file_to_article_object(
        url='https://www.bbc.co.uk/news/articles/cjqep1ew419o', filename='test_file.html'
        )
    article1.fetched_timestamp = datetime.now(timezone.utc)
    article1.parse_all()

    article2 = debug_file_to_article_object(
        url='https://www.bbc.co.uk/news/articles/cjqep1ew419o', filename='test_file2.html'
        )
    article2.fetched_timestamp = datetime.now(timezone.utc)
    article2.parse_all()

    print(article1.parsed == article2.parsed)

###
### End of Testing / Debug functions
###


def request_html(url):
    """ Helper function for using requests to get the HTML """
    try:
        response = requests.get(url, timeout=10)
        # Will raise exception for HTTPError (e.g. 404, off by default)
        response.raise_for_status()
        # For some reason Requests is auto-detecting the wrong encoding so we're getting Mojibakes
        # everywhere. Hard-coding as utf-8 shouldn't cause issues unless BBC change it for
        # random pages which is unlikely
        response.encoding = 'utf-8'
        return response.text
    except requests.exceptions.RequestException as e:
        logger.error(
            'Request Error: URL: %s\n' +
            'Exception __str__:\n%s\n' +
            'Exception Type:\n%s\n',
            url, e, type(e)
            )
        return None




def test_main_loop_storage():
    """ Test function """
    with shelve.open('db/url_id_mapping_db') as db:
        for key, val in db.items():
            print('URL:', key, 'ID:', val)

    debug_table(attrs = ['url'], parsed=['parse_errors', 'headline'])


def main_loop():
    """ ***Work-in-progress***
        This will eventually be the function that repeats at set intervals in order to check for 
        new or updated news articles, store them, note changes, etc.
    """

    # Likely will be called from __main__ at set intervals to keep checking for articles

    # Fully parsed Article objects of the latest news from the homepage
    articles = get_latest_news()

    for article in articles:
        with shelve.open('db/url_id_mapping_db') as db:
            if article.url not in db:
                article.store()
                db[article.url] = article.id
            else:
                print("We've seen this article before:", article.url)
                # This would be where we check for changes between the article objects
                # and only store a new snapshot of it if there are confirmed changes
                # Likely would check that last article object in the list of articles
                # so we can see if it changed from when we last recorded a change


def get_latest_news():
    """ Parses the latest news articles from the BBC news homepage
        Returns a list of article objects
    """
    urls = get_news_urls(debug=5)
    # As get_news_urls() has just been called, there has already been a HTTP request within the
    # last few milliseconds. It's possible the first request of the throttler will be sent too
    # close to the homepage scrape request - so we delay to avoid this
    time.sleep(2)
    articles = urls_to_parsed_articles(urls, delay=5)
    return articles

def get_news_urls(debug=None):
    """ Extracts all the news article URLs from the BBC Homepage
        Returns a list of URL strings
        debug = integer; flag to reduce the number returned for testing purposes
    """
    news_homepage = 'https://www.bbc.co.uk/news'
    news_homepage_html = request_html(news_homepage)
    # In the event of connection issues we don't want to carry on with the function
    if news_homepage_html is None:
        return None
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
        The returned objects should be parsed Article objects ready to store/compare
        urls = list of strings
        delay = float; seconds to use for requests throttling
    """
    # List of request objects to send to the throttler
    reqs = []
    for url in urls:
        request = requests.Request(method='GET', url=url)
        reqs.append(request)

    # Create a custom session to pass to requests_throttler to configure global timeout
    s = requests.Session()
    s.mount('http://', TimeoutHTTPAdapter(timeout=10))
    s.mount('https://', TimeoutHTTPAdapter(timeout=10))

    # Throttler queues all the requests and processes them slowly
    # This step can take a while depending on the delay and number of URLs
    with BaseThrottler(name='base-throttler', delay=delay, session=s) as bt:
        throttled_requests = bt.multi_submit(reqs)

    responses = []
    for tr in throttled_requests:
        # First check for any exceptions
        if tr.exception is not None:
            logger.error(
                'Request Error: URL: %s\n' +
                'Exception __str__:\n%s\n' +
                'Exception Type:\n%s\n',
                tr.request.url, tr.exception, type(tr.exception)
                )
        # The 3rd party library doesn't raise exception for HTTPError so we check
        elif tr.response.status_code != 200:
            logger.error(
                'Request Error: URL: %s\n' +
                'HTTP Error - Status Code: %s\n',
                tr.request.url, tr.response.status_code
                )
        # Anything that gets to here is status code 200
        else:
            responses.append(tr.response)

    res = []
    for response in responses:
        response.encoding = 'utf-8'
        article = Article(response.url)
        article.raw_html = response.text
        # Note: technically not when it is 'fetched' as that happens inside the threading of
        # requests_throttler, so there could be up to a couple of minutes delay on this time
        article.fetched_timestamp = datetime.now(timezone.utc)
        article.parse_all()
        res.append(article)

    return res

def testing_create_table():
    """ Test function """
    con.execute("""
        CREATE TABLE article(
                article_id INTEGER PRIMARY KEY, 
                url, 
                raw_html, 
                fetched_timestamp, 
                headline, 
                body, 
                byline, 
                _timestamp, 
                parse_errors)
                """)

def testing_sqlite():
    """ Testing function: may be an instance method, or maybe not
    """
    article = debug_file_to_article_object(
        url='https://www.bbc.co.uk/news/articles/cw00rgq24xvo', filename='test_file.html'
        )
    article.parse_all()
    row_dict = article.to_row_dict()

    # In the app this will probably be at the beginning of the main_loop function
    con = sqlite3.connect('news_updates_monitor.db')

    # testing_create_table()

    # Format columns string for SQL query
    columns = ', '.join(row_dict.keys())
    # Format values string for SQL query based on named parameter binding syntax
    values = ':' + ', :'.join(row_dict.keys())

    con.execute(f"INSERT INTO article({columns}) VALUES({values})", row_dict)
    con.commit()

    # In the app this will probably be at the end of the main_loop
    con.close()

def dict_factory(cursor, row):
    fields = [column[0] for column in cursor.description]
    return {key: value for key, value in zip(fields, row)}

def testing_table_row_to_article_obj():
    """ Test function to convert an SQLite table row to an Article object
    """
    con = sqlite3.connect('news_updates_monitor.db')
    con.row_factory = dict_factory
    cursor = con.execute("SELECT * FROM article WHERE article_id=1")
    row = cursor.fetchone()
    # Build out the dictionary used in article.parsed (unflatten the object)
    parsed_keys = ['headline', 'body', 'byline', '_timestamp', 'parse_errors']
    parsed_dict = {key: row[key] for key in parsed_keys}
    article = Article(
        url=row['url'],
        raw_html=row['raw_html'],
        fetched_timestamp=row['fetched_timestamp'],
        parsed=parsed_dict
        )
    article.debug_log_print()
    con.close()


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


    # main_loop()
    # test_main_loop_storage()

    # testing_table_row_to_article_obj()

    testing_print_latest_news()
