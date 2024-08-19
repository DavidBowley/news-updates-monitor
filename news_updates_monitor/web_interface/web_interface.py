"""

    ***Web Interface***
    This is the web-based GUI for the database that monitor.py maintains

"""

import logging
from logging.handlers import TimedRotatingFileHandler
import sqlite3
import difflib
import sys

sys.path.append('..')
from article import Article, table_row_to_article, dict_factory


def testing_import():
    con = sqlite3.connect('../monitor/test_db/news_updates_monitor.sqlite3')
    con.execute('PRAGMA foreign_keys = ON')
    con.row_factory = dict_factory
    cursor = con.execute("SELECT * FROM article WHERE article_id=1")
    article = table_row_to_article(cursor.fetchone())
    article.debug_log_print()
    con.close()


def testing_comparison():
    """ Proof of concept for showing visual differences in article objects """
    con = sqlite3.connect('../monitor/test_db/news_updates_monitor.sqlite3')
    con.execute('PRAGMA foreign_keys = ON')
    con.row_factory = dict_factory
    cursor = con.execute("SELECT * FROM article WHERE article_id=171")
    article_a = table_row_to_article(cursor.fetchone())
    cursor = con.execute("SELECT * FROM article WHERE article_id=328")
    article_b = table_row_to_article(cursor.fetchone())

    con.close()

    headline1 = article_a.parsed['headline'].splitlines()
    headline2 = article_b.parsed['headline'].splitlines()
    text1 = article_a.parsed['body'].splitlines()
    text2 = article_b.parsed['body'].splitlines()
    byline1 = article_a.parsed['byline'].splitlines()
    byline2 = article_b.parsed['byline'].splitlines()
    timestamp1 = article_a.parsed['_timestamp'].splitlines()
    timestamp2 = article_b.parsed['_timestamp'].splitlines()


    with open('diff_html/template_top.html', encoding='utf-8') as f:
        template_start = f.read()
    with open('diff_html/template_bottom.html', encoding='utf-8') as f:
        template_end = f.read()

    d = difflib.HtmlDiff(wrapcolumn=71)
    diff_table_headline = d.make_table(headline1, headline2, fromdesc='Headline A', todesc='Headline B')

    d = difflib.HtmlDiff(wrapcolumn=71)
    diff_table_body = d.make_table(text1, text2, fromdesc='Body A', todesc='Body B')

    d = difflib.HtmlDiff(wrapcolumn=71)
    diff_table_byline = d.make_table(byline1, byline2, fromdesc='Byline A', todesc='Byline B')

    d = difflib.HtmlDiff(wrapcolumn=71)
    diff_table_timestamp = d.make_table(timestamp1, timestamp2, fromdesc='Timestamp A', todesc='Timestamp B')

    

    with open('diff_html/diff.html', 'w', encoding='utf-8') as f:
        f.write(template_start)
        f.write(diff_table_headline)
        f.write('\n<br>\n')
        f.write(diff_table_body)
        f.write('\n<br>\n')
        f.write(diff_table_byline)
        f.write('\n<br>\n')
        f.write(diff_table_timestamp)
        f.write(template_end)

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

    # Create a stream handler to print logs to the console
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.DEBUG)
    console_handler.setFormatter(formatter)

    # Add the handlers to the logger
    logger.addHandler(file_handler_debug)
    logger.addHandler(file_handler_info)
    logger.addHandler(console_handler)


    testing_comparison()