"""
    
    ***News Updates Monitor***
    A prototype app that checks for changes made to news articles after they are published

"""

import logging
from logging.handlers import TimedRotatingFileHandler
import time
from datetime import datetime, timezone, timedelta
import sqlite3
import typing
import sys
import asyncio
import configparser

import requests
from requests.adapters import HTTPAdapter
import bs4
# Note: this is my fork of requests_throttler (see requirements.txt)
from requests_throttler import BaseThrottler
import telegram
import schedule

# Disabling Pylint here as it's a false positive from the system path hack
# pylint: disable-next=wrong-import-position
sys.path.append('..')
# Disabling Pylint as it cannot detect the system path hacked local module
# pylint: disable-next=import-error
from article import Article, table_row_to_article, dict_factory


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
        # Disabling Pylint: this is standard usage of logger as global variable
        # pylint: disable-next=possibly-used-before-assignment
        logger.error(
            'Request Error: URL: %s\n' +
            'Exception __str__:\n%s\n' +
            'Exception Type:\n%s\n',
            url, e, type(e)
            )
        return None

def main_loop():
    """ Checks the BBC News homepage for new articles, as well as checks existing articles in the
        database for updates. Uses a scheduling system so that articles are only checked at certain
        times depending on how old they are.        
    """
    # Runs any tasks scheduled by the Schedule module (weekly report for now)
    schedule.run_pending()
    # Update Tracking table to make sure all schedule_levels are up to date
    update_schedule_levels()
    # Find new news articles that we haven't yet seen and add them to the Tracking table
    new_news_to_tracking()
    # Decide which URLs will be fetched this loop based on their schedule_level
    scheduled_urls = calculate_scheduled_urls()
    # Fetch the URLs and convert to parsed article objects (i.e. article snapshots)
    articles = urls_to_parsed_articles(urls=scheduled_urls, delay=5)
    # Process article objects: store new and updated articles in database
    check_articles(articles)

def weekly_report():
    con = sqlite3.connect('test_db/news_updates_monitor.sqlite3')
    con.execute('PRAGMA foreign_keys = ON')
    cursor = con.execute('SELECT COUNT(*) FROM tracking')
    total, = cursor.fetchone()
    cursor = con.execute('SELECT COUNT(*) FROM article')
    total_snapshot, = cursor.fetchone()
    cursor = con.execute('SELECT COUNT(*) FROM fetch')
    total_fetch, = cursor.fetchone()
    telegram_str = ('<b>*** Weekly Report ***</b>\n' +
                'Total unique articles: <b>{:,}</b>\n'.format(total) +
                'Total article snapshots: <b>{:,}</b>\n'.format(total_snapshot) +
                'Total article fetches: <b>{:,}</b>'.format(total_fetch)
                )
    asyncio.run(telegram_bot_send_msg(telegram_str))
    logger.info('Weekly report sent!')

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

        NEW Level 0 = these have been manually removed from the scheduling directly via updating
        the database (likely due to downtime causing massive backlogs of fetches if the fetched
        timestamps were relied on like the rest of the levels). The system should not attempt to
        manually update these levels based on their timestamps, so that we can keep them in the
        database without having the system clog up trying to catch up with the old fetches.
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
    soup = bs4.BeautifulSoup(news_homepage_html, 'lxml')
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
    # Wait so I can actually read how many it's going to attempt before the console gets filled
    time.sleep(5)
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
    session = requests.Session()
    session.mount('http://', TimeoutHTTPAdapter(timeout=10))
    session.mount('https://', TimeoutHTTPAdapter(timeout=10))

    # Throttler queues all the requests and processes them slowly
    # This step can take a while depending on the delay and number of URLs
    with BaseThrottler(name='base-throttler', delay=delay, session=session) as bt:
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

        if status != '200':
            telegram_str = ('<b>*** Request Error ***</b>\n' +
                '<b>URL: </b>' + tr.request.url + '\n' +
                '<b>Fetched Timestamp: </b>' + fetched_timestamp + '\n' +
                '<b>Status: </b>' + status
                )
            asyncio.run(telegram_bot_send_msg(telegram_str))

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

async def telegram_bot_send_msg(msg):
    """ Sends a message using the specified Telegram bot Token and Chat ID from the config.ini file
        Can be disabled using enabled = False in the config file
        Note: this is obviousy not the most efficient way to code the function (reading the config
        file every time for example) however so far in Production it's only been called a handful
        of times per week, so it's unlikely to be a big overhead
    """
    config = configparser.ConfigParser()
    config.read('config.ini')
    bot_enabled = config.getboolean('telegram_bot', 'enabled')
    if bot_enabled:
        token = config['telegram_bot']['token']
        chat_id = config['telegram_bot']['chat_id']
        bot = telegram.Bot(token)
        try:
            async with bot:
                await bot.send_message(text=msg, chat_id=chat_id, parse_mode='html')
        except telegram.error.TelegramError as e:
            logger.error(
                'Telegram Bot error:\n' +
                'Exception __str__: %s\n' +
                'Exception Type: %s',
                e, type(e)
                )


if __name__ == '__main__':

    # Create a logger
    logger = logging.getLogger()
    logger.setLevel(logging.DEBUG)

    formatter = logging.Formatter('%(asctime)s - %(levelname)s: %(message)s')

    # Create separate INFO and DEBUG file logs - 1 each per day with a 30 day rotating backup
    file_handler_debug = TimedRotatingFileHandler(
        'log/debug/debug.log', encoding='utf-8', when='midnight', backupCount=30, utc=True
        )
    file_handler_debug.setLevel(logging.DEBUG)
    file_handler_debug.setFormatter(formatter)

    file_handler_info = TimedRotatingFileHandler(
        'log/info/info.log', encoding='utf-8', when='midnight', backupCount=30, utc=True
        )
    file_handler_info.setLevel(logging.INFO)
    file_handler_info.setFormatter(formatter)

    # Create a stream handler to print logs to the console - only logs INFO
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)

    # Add the handlers to the logger
    logger.addHandler(file_handler_debug)
    logger.addHandler(file_handler_info)
    logger.addHandler(console_handler)

    # Disabling Pylint - this is not a module level constant
    # pylint: disable-next=invalid-name
    interval = 60*15
    try:
        schedule.every().saturday.at("10:00").do(weekly_report)
        while True:
            logger.info('Waking up from sleep...')
            time.sleep(3)
            if is_online():
                main_loop()
                time.sleep(3)
            else:
                logger.error('No internet connection detected, skipping this loop')
            logger.info('Going to sleep for %s minutes...', int(interval / 60))

            for seconds in range(interval, 0, -1):
                m, s = divmod(seconds, 60)
                sys.stdout.write('\t\t\t' + '*'*10 + f' {m:02d}:{s:02d} ' + '*'*10)
                sys.stdout.flush()
                sys.stdout.write("\r")
                time.sleep(1)
    except Exception as e:
        # These exceptions should cause the program to end - I'd like to know about these when they
        # happen so I don't end up having the system down for long periods of time
        logger.critical(
            'Critical failure - app will now exit\n' +
            'Exception __str__:\n%s\n' +
            'Exception Type:\n%s\n',
            e, type(e)
            )
        asyncio.run(telegram_bot_send_msg(
            '<b>*** Fatal Error Detected ***</b>\n' +
            'App is shutting down...\n' + 
            'Please check the logs for more details of the exception.'
            ))
        sys.exit()