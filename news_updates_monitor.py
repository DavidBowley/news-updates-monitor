import requests
import bs4

url = 'https://www.bbc.co.uk/news/articles/cw00rgq24xvo'
page = requests.get(url)

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

print('***Article headline***\n', headline)
print('\n***Article body***\n', body_paragraphs)

