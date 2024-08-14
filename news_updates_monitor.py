"""
    
    ***News Updates Monitor***
    A prototype app that checks for changes made to news articles after they are published

"""

import pprint # pylint: disable=unused-import
              #         For debugging purposes, should be removed later
import logging
import time
from datetime import datetime, timezone, timedelta
import sqlite3
import difflib
import typing

import requests
from requests.adapters import HTTPAdapter
import bs4
# Note: this is my fork of requests_throttler (see requirements.txt)
from requests_throttler import BaseThrottler


class Article():
    """ An Article object represents a snapshot in time of one individual BBC News article
        It can be used to scrape and parse a news article given any valid BBC news URL
        Only designed to work with '/news/...' URLs - does NOT work with Live or Video posts etc.
    """

    def __init__(self, **kwargs):
        """
        url = string
        raw_html = string (default: None)
        fetched_timestamp = ISO8601 datetime as string (default: None)
        soup = bs4.BeautifulSoup.Soup object (default: None)
        parsed = dict {
            'headline': string (default: empty string)
            'body': string (default: empty string)
            'byline': string (default: empty string)
            '_timestamp': ISO8601 datetime as string (default: empty string)
            'parse_errors': boolean (default: False)
            }
        """
        parsed = kwargs.get('parsed')
        if parsed is None:
            parsed = {
            'headline': '',
            'body': '',
            'byline': '',
            '_timestamp': '',
            'parse_errors': False
            }
        self.url = kwargs.get('url')
        self.raw_html = kwargs.get('raw_html')
        self.fetched_timestamp = kwargs.get('fetched_timestamp')
        self.soup = None
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
            self.parsed['_timestamp'] will be an ISO8601 datetime stored as a string
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

    def store(self, con):
        """ Stores the Article object in persistent storage using sqlite
            Is now used to store both brand new articles and updates to existing articles
            con = sqlite3.Connection object (currenlty open DB connection from main_loop() )
        """
        # Remvoing the soup before pickling as it can lead to maximum recursion depth errors
        # Can be re-souped from raw_html if needed
        self.soup = None
        row_dict = self.to_row_dict()
        # Format columns string for SQL query
        columns = ', '.join(row_dict.keys())
        # Format values string for SQL query based on named parameter binding syntax
        values = ':' + ', :'.join(row_dict.keys())
        cursor = con.execute(f"INSERT INTO article({columns}) VALUES({values})", row_dict)
        con.commit()
        article_id = cursor.lastrowid
        logger.debug('Added article object to article table at ID %s: %s',article_id, self.url)
        return article_id

    def to_row_dict(self):
        """ Converts the Article object into a dictionary suitable for passing into the SQLite
            database as a new row. The parsed dicitonary is also flattened out.
        """
        article_dict = self.__dict__
        article_dict.update(article_dict['parsed'])
        del article_dict['parsed']
        del article_dict['soup']
        return article_dict

    def is_copy(self, other):
        """ Boolean function that checks if one Article object is a copy of another
            The check is based on whether their parsed dictionaries have equal values
            This protects against the other elements of the webpage chaninging
            (which they do every few minutes)
        """
        return self.parsed == other.parsed


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
        """ Function that overrides the default requests.Session().send() """
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


def dict_factory(cursor, row):
    """ Factory used with SQLite3.Connection.row_factory
        Produces a dict with column names as keys instead of the default tuple of values
    """
    fields = [column[0] for column in cursor.description]
    return dict(zip(fields, row))

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

def table_row_to_article(row):
    """ Converts an sqlite table row back to its original Article object
        row = dict; output from sqlite3 article table using dict_factory
    """
    # Build out the dictionary used in article.parsed (unflatten the object)
    parsed_keys = ['headline', 'body', 'byline', '_timestamp', 'parse_errors']
    parsed_dict = {key: row[key] for key in parsed_keys}
    # Convert from SQLite Boolean to Python Boolean
    parsed_dict['parse_errors'] = bool(parsed_dict['parse_errors'])
    stored_article = Article(
        url=row['url'],
        raw_html=row['raw_html'],
        fetched_timestamp=row['fetched_timestamp'],
        parsed=parsed_dict
        )
    return stored_article

def main_loop():
    """ Checks the BBC News homepage for new articles, as well as checks existing articles in the
        database for updates. Uses a scheduling system so that articles are only checked at certain
        times depending on how old they are.        
    """
    # Update Tracking table to make sure all schedule_levels are up to date
    update_schedule_levels()
    # Find new news articles that we haven't yet seen and add them to the Tracking table
    new_news_to_tracking()
    # Decide which URLs will be fetched this loop based on their schedule_level
    scheduled_urls = calculate_scheduled_urls()
    # Fetch the URLs and convert to parsed article objects (i.e. article snapshots)
    articles = urls_to_parsed_articles(urls=scheduled_urls, delay=2)
    # Process article objects: store new and updated articles in database
    check_articles(articles)

def update_schedule_levels():
    """ Checks all existing articles from the Tracking table to make sure that their tracking 
        schedule_levels are up-to-date, using the following logic:
        Level 1 = first 3 hours
        Level 2 = over 3 hours to 24 hours
        Level 3 = over 24 to 48 hours
        Level 4 = over 48 hours to 1 week
        Level 5 = over 1 week to 4 weeks
        Level 6 = over 4 weeks
        The duration for each level is up to AND including the timeframe, but greater than the
        previous level's timeframe - the next level starts 1 second after the previous timeframe.
        The first fetched_timestamp on record per URL is the baseline to work out its age.
        Level 6's can be ignored because there's no higher level to move them to.
    """
    schedule_level_duration = {
    1: timedelta(hours=3),
    2: timedelta(hours=24),
    3: timedelta(hours=48),
    4: timedelta(weeks=1),
    5: timedelta(weeks=4),
    }
    con = sqlite3.connect('test_db/news_updates_monitor.sqlite3')
    con.execute('PRAGMA foreign_keys = ON')
    cursor = con.execute(
            """
            SELECT tracking.url, tracking.schedule_level,
                   fetch.fetched_timestamp, MIN(fetch.fetch_id)
            FROM tracking
            JOIN fetch ON tracking.url=fetch.url
            WHERE tracking.schedule_level BETWEEN 1 and 5
            GROUP BY tracking.url
            """
            )
    logger.info('Updating Tracking table schedule_levels for existing articles...')
    time.sleep(2)
    rows = cursor.fetchall()
    counter = 0
    for row in rows:
        url, current_schedule_level, first_fetched_timestamp, _ = row
        first_fetched_timestamp = datetime.fromisoformat(first_fetched_timestamp)
        time_since_fetch = datetime.now(timezone.utc) - first_fetched_timestamp

        if time_since_fetch > schedule_level_duration[5]:
            new_schedule_level = 6
        elif schedule_level_duration[4] < time_since_fetch <= schedule_level_duration[5]:
            new_schedule_level = 5
        elif schedule_level_duration[3] < time_since_fetch <= schedule_level_duration[4]:
            new_schedule_level = 4
        elif schedule_level_duration[2] < time_since_fetch <= schedule_level_duration[3]:
            new_schedule_level = 3
        elif schedule_level_duration[1] < time_since_fetch <= schedule_level_duration[2]:
            new_schedule_level = 2
        elif time_since_fetch <= schedule_level_duration[1]:
            new_schedule_level = 1
        else:
            typing.assert_never(time_since_fetch)

        if new_schedule_level != current_schedule_level:
            # The new level is different to the existing one in DB, so we can update it
            bind = (new_schedule_level, url)
            con.execute(
                """
                UPDATE tracking
                SET schedule_level = ?
                WHERE url = ?
                """, bind)
            counter += 1
        logger.debug(
            '%s \tcurrent_schedule_level: %s\tnew_schedule_level %s',
            url, current_schedule_level, new_schedule_level
            )
    con.commit()
    con.close()
    logger.info('%s schedule_levels updated out of a total %s URLs checked', counter, len(rows))

def new_news_to_tracking():
    """ Identifies any new news articles that haven't been seen by the system yet
        and adds them to the Tracking table
    """
    logger.info('Finding new news articles...')
    time.sleep(2)
    con = sqlite3.connect('test_db/news_updates_monitor.sqlite3')
    con.execute('PRAGMA foreign_keys = ON')
    new_urls = find_new_news()
    for url in new_urls:
        # New URLs always start on schedule_level 1
        con.execute("INSERT INTO tracking VALUES(?, 1)", (url,))
        con.commit()
    logger.info('Added %s new URLs into the Tracking table', len(new_urls))
    con.close()

def find_new_news():
    """ Parses BBC homepage for all news articles and checks if they are new to our system
        Returns a list of URLs that should be added to our system
    """
    con = sqlite3.connect('test_db/news_updates_monitor.sqlite3')
    con.execute('PRAGMA foreign_keys = ON')
    latest_news_urls = get_news_urls()
    cursor = con.execute("SELECT url FROM tracking")
    stored_urls = [row[0] for row in cursor]
    online_urls_not_in_storage = list(set(latest_news_urls) - set(stored_urls))
    con.close()
    return online_urls_not_in_storage

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

def calculate_scheduled_urls():
    """ Works out which URLs from the Tracking table should be fetched. The schedule is as follows:
        Level 1: every 15 minutes
        Level 2: every hour
        Level 3: 3 times a day (every 8 hours)
        Level 4: every day
        Level 5: every week
        Level 6: every month
     """
    logger.info('Calculating which URLs to fetch based on schedule_level...')
    time.sleep(2)
    con = sqlite3.connect('test_db/news_updates_monitor.sqlite3')
    con.execute('PRAGMA foreign_keys = ON')

    all_urls = []
    schedule_results = {}

    # Levels 1's
    # No need to set a schedule assuming the main_loop fires every 15 minutes
    # as this is the interval we want anyway
    cursor = con.execute('SELECT url FROM tracking WHERE schedule_level=1')
    level_1_urls = [row[0] for row in cursor]
    all_urls.extend(level_1_urls)
    schedule_results[1] = len(level_1_urls)

    # Setup schedule levels
    schedule_level = {
    2: timedelta(hours=1),
    3: timedelta(hours=8),
    4: timedelta(days=1),
    5: timedelta(weeks=1),
    6: timedelta(weeks=4)
    }

    # Levels 2 through 6 are only fetched if the required amount of wait_time has elapsed
    for level, wait_time in schedule_level.items():
        urls = []
        # SQL query returns all unique URLs that match the schedule_level as well as the last
        # fetched_timestamp on record (i.e. the last time we tried to request this URL)
        cursor = con.execute(
            """
            SELECT MAX(fetch.fetch_id), tracking.url, fetch.fetched_timestamp FROM tracking
            JOIN fetch ON tracking.url=fetch.url
            WHERE tracking.schedule_level=?
            GROUP BY tracking.url
            """, (level,)
            )
        for row in cursor:
            _, url, last_fetched_timestamp = row
            last_fetched_timestamp = datetime.fromisoformat(last_fetched_timestamp)
            time_since_fetch = datetime.now(timezone.utc) - last_fetched_timestamp
            if time_since_fetch >= wait_time:
                urls.append(url)
        schedule_results[level] = len(urls)
        all_urls.extend(urls)

    schedule_results_str = ''
    for level, res in schedule_results.items():
        schedule_results_str += 'Level ' + str(level) +'s: ' + str(res) + ', '
    logger.info('%s' + 'Total URLs to fetch: %s', schedule_results_str, len(all_urls))
    con.close()
    return all_urls

def urls_to_parsed_articles(urls, delay):
    """ Takes a list of URLs and returns a list of Article objects 
        with raw_html attribute value fetched via the requests_throttler
        The returned objects should be parsed Article objects ready to store/compare
        urls = list of strings
        delay = float; seconds to use for requests throttling
    """
    # pylint: disable=too-many-locals
    #         it was 16/15 - it could be refactored but a lot of effort for the sake of 1 variable

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

    con = sqlite3.connect('test_db/news_updates_monitor.sqlite3')
    con.execute('PRAGMA foreign_keys = ON')
    res = []

    for tr in throttled_requests:
        fetched_timestamp = datetime.now(timezone.utc).isoformat()
        # First check for any exceptions
        if tr.exception is not None:
            logger.error(
                'Request Error: URL: %s\n' +
                'Exception __str__:\n%s\n' +
                'Exception Type:\n%s\n',
                tr.request.url, tr.exception, type(tr.exception)
                )
            status = tr.exception.__class__.__name__
        # The 3rd party library doesn't raise exception for HTTPError so we check
        elif tr.response.status_code != 200:
            logger.error(
                'Request Error: URL: %s\n' +
                'HTTP Error - Status Code: %s\n',
                tr.request.url, tr.response.status_code
                )
            status = str(tr.response.status_code)
        # Anything that gets to here is status code 200
        else:
            tr.response.encoding = 'utf-8'
            article = Article(url=tr.response.url)
            article.raw_html = tr.response.text
            # Note: technically not when it is 'fetched' as that happens inside the threading of
            # requests_throttler, so there could be up to a couple of minutes delay on this time
            # NOTE: the above may no longer be true!
            article.fetched_timestamp = fetched_timestamp
            article.parse_all()
            res.append(article)
            status = '200'

        schedule_level = get_schedule_level(tr.request.url)
        bind = (tr.request.url, schedule_level, fetched_timestamp, status)
        con.execute("""
            INSERT INTO fetch('url', 'schedule_level', 'fetched_timestamp', 'status')
            VALUES(?, ?, ?, ?)
            """, bind)
        con.commit()

    con.close()
    return res

def get_schedule_level(url):
    """ Returns a given URL's current schedule_level from the Tracking table """
    con = sqlite3.connect('test_db/news_updates_monitor.sqlite3')
    con.execute('PRAGMA foreign_keys = ON')
    cursor = con.execute('SELECT schedule_level FROM tracking WHERE url=?', (url,))
    schedule_level = cursor.fetchone()
    con.close()
    if schedule_level is None:
        return None
    return schedule_level[0]

def check_articles(articles):
    """ Takes a list of parsed article objects and checks them for:
        1. New articles: if so they are stored
        2. Existing articles that have changed: if so the new version is stored
        Also updates the fetch table with relevant information
    """
    logger.info('Checking fetched article snapshots for new and updated articles...')
    time.sleep(2)
    con = sqlite3.connect('test_db/news_updates_monitor.sqlite3')
    con.execute('PRAGMA foreign_keys = ON')
    con.row_factory = dict_factory

    c_new = 0
    c_updated = 0
    for article in articles:
        # The highest article_ID that matches the URL contains the most recent changes we've stored
        # (if it exists)
        cursor = con.execute(
            "SELECT * FROM article WHERE url = ? ORDER BY article_id DESC LIMIT 1", (article.url,)
            )
        row = cursor.fetchone()
        if row is None:
            # New article previously unseen
            article_id = article.store(con)
            bind = (False, article_id, article.fetched_timestamp)
            con.execute("""
                UPDATE fetch
                SET changed = ?, article_id = ?
                WHERE fetched_timestamp = ?
                """, bind)
            con.commit()
            c_new += 1
        else:
            stored_article = table_row_to_article(row)
            logger.debug(
                '\nPreviously seen article at %s\n' + 'Latest stored version at ID: %s' +
                '\nFetched article is_copy()? %s\n',
                row['url'], row['article_id'], article.is_copy(stored_article)
                )

            if article.is_copy(stored_article):
                # No changes so just log the fetch data
                bind = (False, article.fetched_timestamp)
                con.execute("""
                    UPDATE fetch
                    SET changed = ?
                    WHERE fetched_timestamp = ?
                    """, bind)
                con.commit()
            else:
                # This is a new version of an existing article, so should be stored
                article_id = article.store(con)
                bind = (True, article_id, article.fetched_timestamp)
                con.execute("""
                    UPDATE fetch
                    SET changed = ?, article_id = ?
                    WHERE fetched_timestamp = ?
                    """, bind)
                con.commit()
                c_updated +=1
    con.close()
    c_total = c_new + c_updated
    logger.info(
        'Stored a total of %s article snapshots (%s new and %s updated articles)',
        c_total, c_new, c_updated
        )

def is_online():
    """ Boolean function that checks whether the internet is connected 
        Checks against https://www.bbc.co.uk
        This covers both if they are down or if my connection is down, as either way
        we will get an exception raised here
    """
    try:
        requests.get('https://www.bbc.co.uk', timeout=10)
        return True
    except requests.exceptions.ConnectionError as e:
        logger.debug(
            'No response from https://www.bbc.co.uk - ' +
            'the internet connection is likely down\n' +
            'Exception __str__:\n%s\n' +
            'Exception Type:\n%s\n',
            e, type(e)
            )
        return False


def testing_looping():
    """ Testing running the main_loop() every 15 minutes """
    # interval = 60*15
    interval = 10 # for debugging - will remove later
    while True:
        logger.info('Waking up from sleep...')
        time.sleep(3)
        if is_online():
            # call main_loop()
            logger.info('Simulating calling main_loop()')
            time.sleep(3)
        else:
            logger.error('No internet connection detected, skipping this loop')
        logger.info('Going to sleep for %s seconds...', interval)
        time.sleep(interval)


def testing_comparison():
    """ Proof of concept for showing visual differences in article objects """
    con = sqlite3.connect('test_db/news_updates_monitor.sqlite3')
    con.execute('PRAGMA foreign_keys = ON')
    con.row_factory = dict_factory
    cursor = con.execute("SELECT * FROM article WHERE article_id=1")
    article_a = table_row_to_article(cursor.fetchone())
    cursor = con.execute("SELECT * FROM article WHERE article_id=31")
    article_b = table_row_to_article(cursor.fetchone())

    con.close()

    text1 = article_a.parsed['body'].splitlines()
    text2 = article_b.parsed['body'].splitlines()

    with open('diff_html/template_top.html', encoding='utf-8') as f:
        template_start = f.read()
    with open('diff_html/template_bottom.html', encoding='utf-8') as f:
        template_end = f.read()

    d = difflib.HtmlDiff(wrapcolumn=75)
    diff_table = d.make_table(text1, text2, fromdesc='From', todesc='To')

    with open('diff_html/diff.html', 'w', encoding='utf-8') as f:
        f.write(template_start)
        f.write(diff_table)
        f.write(template_end)


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
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)

    # Add the handlers to the logger
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)


    main_loop()
