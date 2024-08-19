""" 
    Debugging and testing functions that may be useful in the future

    Note: some of these can't be called from here and would need to be copy/pasted back into
          the main file in order to use them. They weren't originally designed to be called
          from a module but I don't want to remove them fully in case they are useful later.

"""

import sys
import logging

sys.path.append('..')
from article import Article, table_row_to_article, dict_factory

def testing_exceptions():
    """ Test function to make sure Timeout, Connection and other exceptions
        are working via requests_throttler
    """
    urls = [
    'https://github.com/kennethreitz/requests/issues/1236',
    'https://www.github.com',
    'http://fjfklsfjksjdoijfkjsldf.com/',
    'https://www.yahoo.co.uk',
    ]
    articles = urls_to_parsed_articles(urls, delay=5)
    for article in articles:
        article.debug_log_print()

def debug_file_to_article_object(url, filename):
    """ Debugging function: turn an offline file into an article object for testing purposes
        instead of fetching a live URL
        Pulls the HTML into the self.raw_html attribute
    """
    debug_article = Article(url=url)
    with open(filename, encoding='utf-8') as my_file:
        debug_article.raw_html = my_file.read()
    return debug_article

def debug_table(attrs, parsed):
    """ Builds a data table inside a HTML file with all the information from the article objects we
        want to see.
        Currently pulls from template files in /debug_table/ (which is not part of the Git repo)
        but only using it for debugging so far.
        attrs = list of strings; must only include known Article object attributes (but NOT parsed)
        parsed = dictionary keys as per article.parsed[...] to specify specific parsed info
        The ID will always be output as the first column regardless of other details requested
    """
    # pylint: disable=too-many-locals
    # Agree with pylint that this function is too complex, however it's purely for internal
    # debugging and won't be in the final version in this form. If I do decide to reuse parts of
    # this (e.g. to make a dashboard) then I will definitely simplify it and remove some of the
    # variables.
    with open('debug_table/top.html', encoding='utf-8') as f:
        template_start = f.read()
    with open('debug_table/bottom.html', encoding='utf-8') as f:
        template_end = f.read()
    data_table_start = ''
    start_indent = 4
    data_table_start += (
        indent(start_indent) + '<table>\n' +
        indent(start_indent + 2) + '<caption>' + 'Debug Table' + '</caption>\n'
        )
    data_table_start += indent(start_indent+2) + '<tr>\n'
    data_table_start += indent(start_indent+4) + '<th>' + 'ID' + '</th>\n'
    data_table_start += indent(start_indent+4) + '<th>' + 'Snapshot' + '</th>\n'
    for th in attrs:
        data_table_start += indent(start_indent+4) + '<th>' + th + '</th>\n'
    for th in parsed:
        data_table_start += indent(start_indent+4) + '<th>' + th + '</th>\n'
    data_table_start += indent(start_indent+2) + '</tr>'
    # Overwrite existing HTML file if it exists
    with open('debug_table/debug_table.html', 'w', encoding='utf-8') as f:
        f.write(template_start)
        f.write('\n\n' + data_table_start + '\n\n')
    # Start outputing the data rows
    with shelve.open('db/articles_db') as db:
        ids = list(db.keys())
        ids.sort(key=int)
        for _id in ids:
            article_list = db[_id]
            n = 0
            for article in article_list:
                article_dict = article.__dict__
                data_row = ''
                data_row += indent(start_indent+2) + '<tr>\n'
                data_row += indent(start_indent+4) + '<td>' + _id + '</td>\n'
                data_row += indent(start_indent+4) + '<td>' + str(n) + '</td>\n'
                for attr in  attrs:
                    data_row += (
                        indent(start_indent+4) + '<td>' + str(article_dict[attr]) + '</td>\n'
                        )
                for item in parsed:
                    data_row += (
                        indent(start_indent+4) + '<td>' + str(article.parsed[item]) + '</td>\n'
                        )
                data_row += indent(start_indent+2) + '</tr>'
                # Append to existing HTML file
                with open('debug_table/debug_table.html', 'a', encoding='utf-8') as f:
                    f.write(data_row + '\n\n')
                n += 1
        data_table_end = indent(start_indent) + '</table>'
        # End the table and finalise file template - append to existing HTML file
        with open('debug_table/debug_table.html', 'a', encoding='utf-8') as f:
            f.write(data_table_end + '\n\n')
            f.write(template_end)

def indent(spaces):
    """ Returns a string matching the number of spaces needed for the indent
        spaces = integer
    """
    return ' ' * spaces

def testing_indepth_articles():
    """ Test function to try and get the InDepth articles to correctly parse the headline """
    article = debug_file_to_article_object('https://www.bbc.co.uk/news/articles/c4gz8934wrro', 'test_files/indepth_test_isolate.html')
    article.debug_parse_all()
    # article.debug_log_print()


if __name__ == '__main__':

    # Create a logger
    logger = logging.getLogger()
    logger.setLevel(logging.DEBUG)

    formatter = logging.Formatter('%(asctime)s - %(levelname)s: %(message)s')
    
    # Create a stream handler to print logs to the console
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.DEBUG)
    console_handler.setFormatter(formatter)

    # Add the handlers to the logger
    logger.addHandler(console_handler)

    testing_indepth_articles()