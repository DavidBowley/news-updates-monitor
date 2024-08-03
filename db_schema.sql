CREATE TABLE article (
  article_id INTEGER PRIMARY KEY,
  url TEXT,
  raw_html TEXT,
  fetched_timestamp TEXT,
  headline TEXT,
  body TEXT,
  byline TEXT,
  _timestamp TEXT,
  parse_errors INTEGER -- Boolean as INT
);

CREATE TABLE tracking (
  url TEXT NOT NULL PRIMARY KEY,
  schedule_level INTEGER
);

CREATE TABLE fetch (
  fetch_id INTEGER PRIMARY KEY,
  url TEXT,
  fetched_timestamp TEXT,
  changed INTEGER, -- Boolean as INT
  article_id INTEGER,
  FOREIGN KEY(url) REFERENCES tracking(url),
  FOREIGN KEY(article_id) REFERENCES article(article_id)
);
