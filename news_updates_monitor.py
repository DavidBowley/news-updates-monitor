import requests
import bs4
from datetime import datetime

class Article():
    """ An Article object represents one individual BBC News article
        It can be used to scrape and parse a news article given any valid BBC news URL
        Only designed to work with '/news/...' URLs - does NOT work with Live or Video posts etc.
    """

    def __init__(self, url):
        self.url = url
        self.raw_HTML = ''
        self.soup = None
        self.headline = ''
        self.body = ''
        self.byline = []
        self.datetime = []
        # Plenty more to add here but will stop for now...

    def __str__(self):
        """ This may change for now but I need to pick something... 
            Going for both URL and headline for now
        """
        return self.headline + '\n' + self.url

    def get_HTML(self):
        response = requests.get(self.url)
        # For some reason Requests is auto-detecting the wrong encoding so we're getting Mojibakes everywhere
        # Hard-coding as utf-8 shouldn't cause issues unless BBC change it for random pages which is unlikely
        response.encoding = 'utf-8'
        self.raw_HTML = response.text

    def parse_all(self):
        self.soup = bs4.BeautifulSoup(self.raw_HTML, 'lxml')
        self.parse_headline()
        self.parse_body()
        self.parse_byline()
        self.parse_datetime()

    def parse_headline(self):
        self.headline = self.soup.h1.string
    
    def parse_body(self):
        text_block_divs = self.soup.find_all('div', attrs={'data-component': 'text-block'})
        for div in text_block_divs:
            for p in div.find_all('p'):
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
            self.byline = None
        else:
            for string in byline_block_div.strings:
                self.byline.append(string)

    def parse_datetime(self):
        """ At the time of writing, each visible date was inside a <time> element with a datetime attribute that conforms to ISO 8601
            Although a max of 2 <time> elements have only ever been seen, for debugging purposes we will collect all of them to confirm this assumption
            self.datetime will be a list of Datetime objects
        """
        time_tag = self.soup.find_all('time', attrs={'data-testid': 'timestamp'})
        for tag in time_tag:
            iso_datetime = tag['datetime']
            self.datetime.append(datetime.fromisoformat(iso_datetime))

url = 'https://www.bbc.co.uk/news/articles/cw00rgq24xvo'
# url = 'https://www.bbc.co.uk/news/articles/c4ngk17zzkpo'
# url = 'https://www.bbc.co.uk/news/articles/cq5xel42801o'
# url ='https://www.bbc.co.uk/news/articles/cl4y8ljjexro'

test_article = Article(url)
test_article.get_HTML()
test_article.parse_all()

print('***Article headline***\n' + test_article.headline)
print('\n***Article body***\n' + test_article.body)
print('\n***Byline***')

for string in test_article.byline:
    print(string)

print('\n***Date Info***')
print(test_article.datetime)