"""

    ***Article class***
    Contains Article class and other helper functions

"""

import logging

import bs4


logger = logging.getLogger(__name__)

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

def dict_factory(cursor, row):
    """ Factory used with SQLite3.Connection.row_factory
        Produces a dict with column names as keys instead of the default tuple of values
    """
    fields = [column[0] for column in cursor.description]
    return dict(zip(fields, row))