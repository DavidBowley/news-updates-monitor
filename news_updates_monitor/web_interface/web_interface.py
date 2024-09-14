"""

    ***Web Interface***
    This is the web-based GUI for the database that monitor.py maintains

"""

import logging
from logging.handlers import TimedRotatingFileHandler
import sqlite3
import difflib
import sys
import math
from datetime import datetime, timezone
import pprint

import jinja2
from flask import Flask, render_template, request

sys.path.append('..')
from article import Article, table_row_to_article, dict_factory


app = Flask(__name__)


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
    cursor = con.execute("SELECT * FROM article WHERE article_id=1604")
    article_a = table_row_to_article(cursor.fetchone())
    cursor = con.execute("SELECT * FROM article WHERE article_id=1693")
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

    # TODO: make this some kind of loop as there's no need for all this repetition
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

def testing_jinja():
    """ Test function """
    environment = jinja2.Environment()
    template = environment.from_string("Hello, {{name}}!")
    print(template.render(name='World'))


def convert_datetime(val):
    """ Sqlite3 Converter function - ISO 8601 datetime to datetime.datetime object."""
    return datetime.fromisoformat(val.decode())


@app.route('/')
def home():
    """ Flask homepage """
    # Contains a list of all unique articles
    # Basic version will show X per page with a pagination component, latest articles first

    # Count the number of rows in the Tracking table (unique articles)
    con = sqlite3.connect('../monitor/test_db/news_updates_monitor.sqlite3')
    con.execute('PRAGMA foreign_keys = ON')
    cursor = con.execute('SELECT COUNT(*) FROM tracking')
    total, = cursor.fetchone()

    # hard-coded an arbitrary 100 for now
    rows_per_page = 100
    # page requested via the query string
    page = request.args.get('page')
    # Validate query string - nothing entered at all defaults to page 1
    if page and page.isdigit():
        page = max(int(page), 1)
    else:
        page = 1
    
    # For handling pagination buttons
    page_prev, page_next = max(page - 1, 1), page + 1
    # math.ceil because any remainder left must be on its own page, even if only one row
    total_pages = int(math.ceil(total / rows_per_page))
    # Ensure requested page isn't too high, return the highest possible if it is
    page = max(min(page, total_pages), 1)
    # How many rows to exclude from the beginning of the query, depending on what page we're on
    offset = (page - 1) * rows_per_page
    # Make sure page_next can't exceed the total number of pages
    page_next = min(page + 1, total_pages)
    # The row number of the first row on the page
    page_start = offset + 1
    # The row number of the last row on the page (may have less than the previous full pages)
    page_end = min(total, page_start + rows_per_page - 1)

    bind = (rows_per_page, offset)
    cursor = con.execute('SELECT url, rowid FROM tracking ORDER BY rowid DESC LIMIT ? OFFSET ?', bind)
    article_urls = cursor.fetchall()

    cursor = con.execute('SELECT COUNT(*) FROM article')
    total_snapshot, = cursor.fetchone()

    cursor = con.execute('SELECT COUNT(*) FROM fetch')
    total_fetch, = cursor.fetchone()


    # TODO: add logic for if the database is empty (i.e the first run)

    con.close()

    return render_template(
        'index.html',
        total=total,
        page=page,
        total_pages=total_pages,
        offset=offset, # debug only
        page_prev=page_prev,
        page_next=page_next,
        page_start=page_start,
        page_end=page_end,
        article_urls=article_urls,
        total_snapshot=total_snapshot,
        total_fetch=total_fetch
        )

@app.route('/article')
def article():
    """ Article page - one per unique article URL """
    con = sqlite3.connect('../monitor/test_db/news_updates_monitor.sqlite3')
    con.execute('PRAGMA foreign_keys = ON')
    con.row_factory = dict_factory
    url = request.args.get('url')

    cursor = con.execute(
            'SELECT * FROM article WHERE url = ? ORDER BY article_id DESC LIMIT 1', (url,)
            )
    row = cursor.fetchone()
    latest_article = table_row_to_article(row)
    con.close()

    # Open a new connection without dict_factory
    con = sqlite3.connect('../monitor/test_db/news_updates_monitor.sqlite3')
    con.execute('PRAGMA foreign_keys = ON')
    cursor = con.execute(
            'SELECT COUNT(*) FROM article WHERE url = ?', (url,)
            )
    snapshots, = cursor.fetchone()
    cursor = con.execute(
            'SELECT COUNT(*) FROM fetch WHERE url = ?', (url,)
            )
    fetches, = cursor.fetchone()
    cursor = con.execute(
            'SELECT article_id FROM article WHERE url = ?', (url,)
            )
    article_ids = []
    for row in cursor:
        article_ids += row

    # Tuple giving version info and article_ids for different comparision versions
    # Format: ( (version_a, version_b), id_a, id_b )
    compare_ids = []
    for i in range(len(article_ids) - 1):
        versions = (i + 1, i + 2)
        compare_ids.append((versions, article_ids[i], article_ids[i+1]))

    cursor = con.execute(
            'SELECT schedule_level FROM tracking WHERE url = ?', (url,)
            )
    schedule_level, = cursor.fetchone()

    con.close()

    return render_template(
        'article.html',
        latest_article=latest_article,
        snapshots=snapshots,
        fetches=fetches,
        schedule_level=schedule_level,
        article_ids=article_ids,
        compare_ids=compare_ids
        )

@app.route('/compare')
def compare():
    """ Compare page - compares one article version to another version
        Recieves query string with 2 article IDs that can be used for comparison
    """
    id_a = request.args.get('id_a')
    id_b = request.args.get('id_b')
    version_a = request.args.get('version_a')
    version_b = request.args.get('version_b')
    url = request.args.get('url')

    con = sqlite3.connect('../monitor/test_db/news_updates_monitor.sqlite3')
    con.execute('PRAGMA foreign_keys = ON')
    con.row_factory = dict_factory
    cursor = con.execute("SELECT * FROM article WHERE article_id=?", (id_a,))
    article_a = table_row_to_article(cursor.fetchone())
    cursor = con.execute("SELECT * FROM article WHERE article_id=?", (id_b,))
    article_b = table_row_to_article(cursor.fetchone())
    con.close()

    parsed_parts = list(article_a.parsed.keys())
    parsed_parts.remove('parse_errors')
    diff_tables = []

    for part in parsed_parts:
        snapshot_a = article_a.parsed[part]
        if snapshot_a is not None:
            snapshot_a = snapshot_a.splitlines()
        else:
            snapshot_a = ['']
        snapshot_b = article_b.parsed[part]
        if snapshot_b is not None:
            snapshot_b = snapshot_b.splitlines()
        else:
            snapshot_b = ['']
        d = difflib.HtmlDiff(wrapcolumn=71)
        diff_table = d.make_table(
            snapshot_a,
            snapshot_b,
            fromdesc=f'{part.strip('_').title()} Version {version_a}',
            todesc=f'{part.strip('_').title()} Version {version_b}'
            )
        diff_tables.append(diff_table)

    return render_template(
        'compare.html',
        id_a=id_a,
        id_b=id_b,
        version_a=version_a,
        version_b=version_b,
        url=url,
        diff_tables=diff_tables,
        )

@app.route('/fetch_history')
def fetch_history():
    """ Shows all the fetch timestamps for the given article URL """
    url = request.args.get('url')
    con = sqlite3.connect('../monitor/test_db/news_updates_monitor.sqlite3', detect_types=sqlite3.PARSE_COLNAMES)
    con.execute('PRAGMA foreign_keys = ON')
    cursor = con.execute(
            'SELECT fetched_timestamp as "fetched_timestamp [datetime]", status, schedule_level FROM fetch WHERE url = ?', (url,)
            )
    fetches = cursor.fetchall()

    # Format the timestamp string
    fetches_strftime = []
    for fetch in fetches:
        new_fetch = []
        for col in fetch:
            if isinstance(col, datetime):
                col = col.strftime('%d %b %Y, %H:%M:%S')
            new_fetch.append(col)
        fetches_strftime.append(tuple(new_fetch))
    fetches = fetches_strftime

    return render_template('fetch_history.html', url=url, fetches=fetches)


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

    sqlite3.register_converter("datetime", convert_datetime)

    app.run(debug=True)
    
