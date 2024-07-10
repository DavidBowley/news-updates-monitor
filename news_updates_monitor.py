import requests
import bs4

url = 'https://www.bbc.co.uk/news/articles/cw00rgq24xvo'
# url = 'https://www.bbc.co.uk/news/articles/c4ngk17zzkpo'
# url = 'https://www.bbc.co.uk/news/articles/cq5xel42801o'
# url ='https://www.bbc.co.uk/news/articles/cl4y8ljjexro'
page = requests.get(url)
# For some reason Requests is auto-detecting the wrong encoding so we're getting Mojibakes everywhere
# Hard-coding as utf-8 shouldn't cause issues unless BBC change it for random pages which is unlikely
page.encoding = 'utf-8'

soup = bs4.BeautifulSoup(page.text, 'lxml')
headline = soup.h1.string

text_block_divs = soup.find_all('div', attrs={'data-component': 'text-block'})

body_paragraphs = ''

for div in text_block_divs:
    for p in div.find_all('p'):
        # Delete class attribute from each parent <p>
        del p['class']
        # Do the same for each descendant of each <p> that is a Tag object (e.g. <a href> and <b>)
        for tag in p.descendants:
            if isinstance(tag, bs4.element.Tag):
                del tag['class']
        body_paragraphs += str(p)

print('***Article headline***\n' + headline)
print('\n***Article body***\n' + body_paragraphs)
print('\n***Byline***')

byline_block_div = soup.find('div', attrs={'data-component': 'byline-block'})
if byline_block_div is None:
    # There is no byline-block present (some articles don't have one)
    print('There is no parsable byline data present in the article')
else:
    # The data is too inconsistent to create a reliable mapping (e.g. Author, Job Title, etc.) as different authors don't all have the same types of data
    # It is probably possible with some work, but as the main focus of the project is comparing article headlines/body this will be left as a list of strings for now
    for string in byline_block_div.strings:
        print(string)