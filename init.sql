CREATE DATABASE blog;
USE blog;

-- Main table
CREATE TABLE blog_posts (
  post_id int(4) NOT NULL AUTO_INCREMENT,
  title tinytext NOT NULL,
  url_title tinytext NOT NULL,
  post_date date NOT NULL,
  description mediumtext NOT NULL,
  text longtext NOT NULL,
  PRIMARY KEY (post_id),
  FULLTEXT KEY text (text)
) ENGINE=Aria DEFAULT CHARSET=utf8;

-- This is where contact info challenges are stored
CREATE TABLE email_challenges (
  challenge_id smallint(5) unsigned NOT NULL AUTO_INCREMENT,
  word char(24) NOT NULL,
  creation_time timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (challenge_id)
) ENGINE=Aria DEFAULT CHARSET=utf8;

-- Delete old email challenges after 3 minutes.
CREATE EVENT delete_old_email_challenges ON SCHEDULE EVERY 3 MINUTE DO DELETE FROM email_challenges WHERE TIMESTAMPDIFF(MINUTE, creation_time, NOW()) > 3;

-- Set up user accounts
-- Be sure to change passwords!!
-- reader: user for blog.py
CREATE USER reader IDENTIFIED BY 'defreaderpw';
GRANT SELECT ON  blog.* TO reader;
GRANT INSERT, DELETE ON blog.email_challenges TO reader;
-- writer: user for post.py
CREATE USER writer IDENTIFIED BY 'defwriterpw';
GRANT SELECT, INSERT, UPDATE ON blog.blog_posts TO writer;
