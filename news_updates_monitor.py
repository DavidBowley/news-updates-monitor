import requests
from bs4 import BeautifulSoup

url = 'https://www.bbc.co.uk/news/articles/cg33v21weg3o'
page = requests.get(url)

soup = BeautifulSoup(page.text, 'lxml')
print(soup.title)