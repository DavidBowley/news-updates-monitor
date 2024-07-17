import requests
import bs4
from datetime import datetime
import logging
import time

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
                self.body += str(p)

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
                self.byline.append(string)

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


def testing_Article_class():
    # url = 'https://www.bbc.co.uk/news/articles/cw00rgq24xvo'
    # url = 'https://www.bbc.co.uk/news/articles/c4ngk17zzkpo'
    # url = 'https://www.bbc.co.uk/news/articles/cq5xel42801o'
    # url ='https://www.bbc.co.uk/news/articles/cl4y8ljjexro'
    # BBC In-depth article
    url = 'https://www.bbc.co.uk/news/articles/c0www3qvx2zo' 
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

def get_news_urls():
    """ Extracts all the news article URLs from the BBC Homepage
        Returns a list of URL strings
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
    return news_urls

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

def testing_get_latest_news():
    # urls = get_news_urls()
    urls = ['https://www.bbc.co.uk/news/articles/cw00rgq24xvo', 'https://www.bbc.co.uk/news/articles/c4ngk17zzkpo']
    # As get_news_urls() has just been called, there has already been a HTTP request within the last few milliseconds
    # It's possible the first request of the throttler will be sent too close to the homepage scrape request - so we delay to avoid this
    time.sleep(5)
    articles = urls_to_parsed_articles(urls, delay=2)
    for article in articles:
        article.debug_log_print()


# Playing around with this debug table but I think it could possibly work as a Class as all these functions will modify the table
# Long-term it might be better as its own package and imported because I can see having the ability to build out debug tables with
# whatever data I want could be quite useful

# Currently pulls from template files in /debug_table/ (which is not part of the Git repo) but only using it for debugging so far

def debug_table():
    """ Builds a data table inside a HTML file with all the information from the article objects we want to see
        [work in progress]
    """
    with open('debug_table/top.html', encoding='utf-8') as f:
        template_start = f.read()
    with open('debug_table/bottom.html', encoding='utf-8') as f:
        template_end = f.read()

    # Construct data table
    # Note: in final version this won't be stored in a variable as that would store entire article database here
    # We'll be taking one article object at a time and writing it to the data table in the HTML file
    # so there's only ever one article object in memory during this process at any one time
    data_table = debug_table_construct(start_indent=4, caption='Caption goes here')

    with open('debug_table/debug_table.html', 'w', encoding='utf-8') as f:
        f.write(template_start)
        f.write('\n\n' + data_table + '\n\n')
        f.write(template_end)

def debug_table_construct(start_indent, caption):
    # Notes for taking from prototype to working function (note this function might be merged with its caller also)
    # 
    # 1. Outer for loop iterates through article objects in persistent storage
    # 2. Inner for loop iterates through debug_attrs to add the table cells for each row
    # 3. Number of columns to add is determined by the length of debug_attrs and the other for loops in use
    #    This allows a customised data table from 1 column up to as many attributes as the object has
    # 4. So that the entire database isn't loaded into memory...
    #    ... syncronise pulling the article object from persistent storage with the actual writing into the HTML file
    #        e.g. for every article pulled (one at a time) the HTML file is written to (appended) with the next data table row
    #        so there's never more than one article's worth of data loaded into memory at a time while writing the table

    # Note: I know this makes no sense to place it here and likely this function needs to be rewritten - but this is just to test the principle
    article = debug_file_to_article_object('test_file.html')
    article2 = debug_file_to_article_object('test_file2.html')
    article.parse_all()
    article2.parse_all()
    # In the proper version we'll be traversing through a list of articles, but for now just setting two separate dictionaries and hard-coding table data
    article_dict = article.__dict__
    article_dict2 = article2.__dict__
    
    # Simulate list of attributes I want to show in debug table
    debug_attrs = ['headline', 'body', 'byline', 'timestamp']

    data_table = ''
    # ex_column_headers = ['First column header', 'Second column header', 'Third column header', 'Fourth column header', 'Fifth column header']
    # ex_table_cells = ['Test' for i in range(5)]
    # Begin <table> and add <caption>
    data_table += indent(start_indent) + '<table>\n' + indent(start_indent + 2) + '<caption>' + caption + '</caption>\n'
    # Add first <tr> with table column headers
    data_table += indent(start_indent+2) + '<tr>\n'
    for th in  debug_attrs:
        data_table += indent(start_indent+4) + '<th>' + th + '</th>\n'
    data_table += indent(start_indent+2) + '</tr>\n'
    # Row 2
    data_table += indent(start_indent+2) + '<tr>\n'
    for attr in  debug_attrs:
        data_table += indent(start_indent+4) + '<td>' + str(article_dict[attr]) + '</td>\n'
    data_table += indent(start_indent+2) + '</tr>\n'
    # Row 3
    data_table += indent(start_indent+2) + '<tr>\n'
    for attr in  debug_attrs:
        data_table += indent(start_indent+4) + '<td>' + str(article_dict2[attr]) + '</td>\n'
    data_table += indent(start_indent+2) + '</tr>\n'
    # End table
    data_table += indent(start_indent) + '</table>'
    return data_table

def indent(spaces):
    """ Returns a string matching the number of spaces needed for the indent
        spaces = integer
    """ 
    return ' ' * spaces


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
    debug_table()
    # testing_access_filtered_obj_attrs()

