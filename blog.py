#!/usr/bin/env python3
#LightBlog: a lightweight Python blogging application.
#Copyright (C) 2017  Dylan Spriggs
#
#This program is free software; you can redistribute it and/or modify
#it under the terms of the GNU General Public License as published by
#the Free Software Foundation; either version 2 of the License, or
#(at your option) any later version.
#
#This program is distributed in the hope that it will be useful,
#but WITHOUT ANY WARRANTY; without even the implied warranty of
#MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#GNU General Public License for more details.
#
#You should have received a copy of the GNU General Public License along
#with this program; if not, write to the Free Software Foundation, Inc.,
#51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.
import os
import re
import sys
import cgi
import cgitb
import random
import datetime
# be sure to install mysql-connector!
# pip3 install mysql-connector
import mysql.connector

sql_config = {
	'unix_socket': '/var/run/mysqld/mysqld.sock',
	# be sure to use a valid username/password
	'user': 'reader',
	'password': 'defreaderpw',
	'database': 'blog',
	'raise_on_warnings': True
}

template_config = {
	'post_template' : '/var/www/home_temp.html',
	'archive_template': '/var/www/archive_temp.html',
	'email_challenge' : '/var/www/email_temp1.html',
	'email_success' : '/var/www/email_temp2.html',
	'wordlist' : '/var/www/wordlist'
}

def handle_request():
	"""
	This function is where execution of this code begins.
	It figures out what the page to serve based on the CGI request passed by the web server.
	"""
	form = cgi.FieldStorage()
	request_type = os.getenv('REQUEST_METHOD')
	if request_type == 'GET':
		query = form.getvalue('p')
		if query is None:
			serve_post()
		elif query == 'archive':
			serve_default_archive()
		elif query == 'contact':
			serve_email_challenge()
		elif re.match('^[a-z0-9\-]+$', query):
			serve_post(query)
		else:
			serve_error('404 Not Found', 'The page you\'re requesting doesn\'t exist.')
	elif request_type == 'POST':
		if 'search' in form:
			serve_search_archive(form.getvalue('search'))
		elif 'challenge' in form:
			check_email_challenge(form.getvalue('challenge'))
		else:
			serve_error('400 Bad Request', 'Bad POST request.')
	else:
		serve_error('400 Bad Request', request_type + " is not a supported http method.")
		sys.exit(1)

def log_print(*args, **kwargs):
	"""
	A wrapper around print() that prints to stderr.
	On Apache, stderr gets logged.
	"""
	print(*args, file = sys.stderr, **kwargs)

def print_headers(headers = [], mime_type = 'text/html'):
	"""
	Prints HTTP headers to stdout.
	Takes a list of HTTP headers as strings.
	Optional mime_type variable can be used to modify Content-Type header
	"""
	for header in headers:
		print(header + '\r\n', end = '')
	print('Content-Type:', mime_type + '\r\n\r\n', end = '')

def to_utf8(field):
	"""
	Used to turn bytearry type into utf-8 encoding.
	Needed because mysql-connector returns data as bytearray
	"""
	return field.decode('utf8') if type(field) is bytearray else field

class SQLcon:
	"""
	Opens a connection to MySQL/MariaDB.
	sql_config must be passed to the constructor to open the connection.
	"""
	queries = {
		'get_number_posts'		: "SELECT COUNT(*) AS max FROM blog_posts;",
		'get_first_post'		: "SELECT title, url_title, post_date, text FROM blog_posts ORDER BY post_date DESC LIMIT 1;",
		'get_post' 				: "SELECT title, post_date, text FROM blog_posts WHERE url_title = %s;",
		'get_title_and_desc'	: "SELECT url_title, title, description FROM blog_posts ORDER BY post_date DESC LIMIT 20;",
		'search_db'				: "SELECT title, url_title, description, Match(text) Against(%s WITH QUERY EXPANSION) AS rank FROM blog_posts ORDER BY rank DESC LIMIT 20;",
		'get_ordered_url_titles': "SELECT url_title FROM blog_posts ORDER BY post_date DESC;",
		'insert_challenge'		: "INSERT INTO email_challenges(word, creation_time) VALUES (%s, NOW());",
		'find_challenge'		: "SELECT challenge_id FROM email_challenges WHERE word = %s;",
		'delete_challenge'		: "DELETE FROM email_challenges WHERE challenge_id = %s;",
	}
	def __init__(self, config):
		"""
		Sets up connection.
		Sends a 500 error to web sever and exits with status 1 if connection fails.
		"""
		try:
			self.conn = mysql.connector.connect(**config)
		except mysql.connector.Error as e:
			print("SQL error: {}".format(e), file = sys.stderr)
			serve_error('500 Internal Error', 'Something went wrong. Please Try again later')
			exit(1)

	def execute(self, query, *parameters, commit = False):
		"""
		Executes one of the queries defined above in the queries dictionary.
		If the query takes any parameters, those must be passed to this function as well.
		If the query is an INSERT, UPDATE, or DELETE, the commit variable must be set to true.
		Any resulting data is returned as a tuple of dictionaries, with each row being a dictionary.
		In every dictionary, the keys are the column names and values the value of that particular row.
		If only one row is returned, the dictionary for that row is not wrapped in a tuple.
		"""
		try:
			# set up a temporary cursor
			cur = self.conn.cursor(prepared = True)
			# execute the query
			cur.execute(self.queries[query], parameters)
			if commit:
				self.conn.commit()
				return None
			rows = cur.fetchall()
			if cur.rowcount == 0:
				return None
			elif cur.rowcount == 1:
				return dict(
					[(col_name, to_utf8(field)) for col_name, field in zip(cur.column_names, rows[0])]
				)
			else: 
				ret = list()
				for row in rows:
					ret.append(dict(
						[(col_name, to_utf8(field)) for col_name, field in zip(cur.column_names, row)]
					))
				return tuple(ret)
		except KeyError:
			log_print("SQL error: That query is not defined")
			return None
		except mysql.connector.Error as e:
			log_print("SQL error: {}".format(e))
			return None	
		finally:
			cur.close()

	def __del__(self):
		"""
		Closes connection when no references of this object are left.
		"""
		self.conn.close()

class HTMLtemplate:
	"""
	This class provides a less verbose way of printing HTML into a premade template.
	It should be used in a "with" block like:

	with HTMLtemplate("/path/to/template/") as temp:
		...

	It is initialized with the path to the premade HTML template.
	"""
	def __init__(self, template_path):
			self.template_path = template_path
			self.inserts = dict()
			self.current_marker = str()
			self.current_list_index = list()

	def __enter__(self):
		self.fh = open(self.template_path, 'r')
		return self

	def __exit__(self, exc_type, exc_value, traceback):
		printed = False
		for line in self.fh:
			for mark in self.inserts.keys():
				if line.find(mark) != -1:
					self._print_list(self.inserts[mark])
					printed = True
					break
			if not printed:
				print(line, end = '')
			printed = False
		self.fh.close()
	
	def _print_list(self, l):
		for i in l:
			if isinstance(i, list):
				self._print_list(i)
			else:
				print(i)

	def _append_at_marker(self, text):
		current_list = self.inserts[self.current_marker]
		append_method = lambda x: current_list.append(x)
		if self.current_list_index != []:
			append_method = lambda x: current_list.insert(-1, x)
			for i in self.current_list_index:
				current_list = current_list[i]
		if isinstance(text, list):
			self.current_list_index.append(len(current_list) if self.current_list_index == [] else len(current_list) - 1)
		append_method(text)

	def set_insert(self, marker):
		"""
		There ought to be an HTML comment in the template specifying where generated HTML should be printed.
		This function sets the current insertion point with an argument like '<!--I want my HTML printed here-->'
		"""
		if not marker in self.inserts:
			self.inserts[marker] = []
		self.current_marker = marker
		self.current_list_index = []

	def jump(self, levels = 0):
		"""
		Sometimes HTML elements need to be nested.
		If something like a div is printed, by default, every element after will be printed inside the div.
		This function can be called when an element needs to be 'jumped' out of, so that everything will be printed outside after that HTML element.
		It can take an optional argument, 'levels', which is zero by default.
		Zero makes everything printed after unnested.
		One jumps to the nest level BELOW the zeroth level.
		Two jumps to the nest level BELOW two, and so on.
		"""
		if levels <= 0:
			self.current_list_index = []
		else:
			for i in range(levels if levels < len(self.current_list_index) else len(self.current_list_index)):
				self.current_list_index.pop()

	def h(self, text, level = 2):
		"""
		Wrap text in <h(n)> tags where n is passed in the optional level argument.
		level is 2 by default.
		"""
		self._append_at_marker('<h{l}>{t}</h{l}>'.format(l = str(level), t = text))
	
	def hr(self):
		"""
		Print <hr />.
		"""
		self._append_at_marker('<hr />')

	def p(self, text):
		"""
		Print 'text' inside <p> tags
		"""
		self._append_at_marker('<p>{}</p>'.format(text))

	def append_raw(self, raw):
		"""
		Print plain string, no HTML.
		"""
		self._append_at_marker(raw)

	def a(self, url, text):
		"""
		Print hyperlink.
		'url' is the URL.
		'text' is the hyperlink text.
		"""
		self._append_at_marker('<a href="{u}">{t}</a>'.format(u = url, t = text))

	def li(self):
		"""
		Print list element.
		Other elements are nested inside of this element after this is called.
		It must be jump()'ed out of to print unnested elements.
		"""
		self._append_at_marker(['<li>', '</li>'])

	def div(self, identifier):
		"""
		Prints a div with id of 'identifier' argument.
		Other elements are nested inside of this element after this is called.
		It must be jump()'ed out of to print unnested elements.
		"""
		self._append_at_marker(['<div id="{}">'.format(identifier), '</div>'])

def serve_post(url_title = None):
	"""
	Serves a blog post.
	If no post url is provided by handle_request(), it prints the newest post.
	"""
	sql = SQLcon(sql_config)
	if url_title is None:
		post = sql.execute('get_first_post')
		url_title = post['url_title']
	else:
		post = sql.execute('get_post', url_title)	
		if post is None:
			serve_error('404 Not Found', 'Sorry. That blog post doesn\'t exist.')
			return
	print_headers()
	with HTMLtemplate(template_config['post_template']) as temp:
		temp.set_insert('<!--post-->')
		temp.h(post['title'])
		temp.h(post['post_date'].strftime('%b. %d, %Y'), level = 3)
		temp.append_raw(post['text'])
		temp.hr()
		prev_url, next_url = get_seq_url_titles(url_title, sql)
		temp.set_insert('<!--links-->')
		if prev_url is not None:
			temp.div('prev')
			temp.a('/?p=' + prev_url, 'Previous Post')
			temp.jump()
		if next_url is not None:
			temp.div('next')
			temp.a('/?p=' + next_url, 'Next Post')
			temp.jump()
	
def get_seq_url_titles(url_title, sql):
	"""
	Gets the urls of next oldest post and previous newest post.
	In addition to taking a url_title, it takes a SQLcon object to do its work.
	"""
	max_offset = sql.execute('get_number_posts')['max'] - 1
	titles = sql.execute('get_ordered_url_titles')
	prev_url = next_url = None
	for offset, row in enumerate(titles):
		if row['url_title'] == url_title:
			if offset != 0:
				prev_url = titles[offset - 1]['url_title']
			if offset != max_offset:
				next_url = titles[offset + 1]['url_title']
	return (prev_url, next_url)

def serve_default_archive():
	"""
	First search page before a user tries to search for something.
	Prints a list links to the ten newest posts.
	"""
	sql = SQLcon(sql_config)
	posts = sql.execute('get_title_and_desc')
	if posts is None:
		serve_error('500 Internal Error', 'Something went wrong. Please Try again later')
		return
	print_headers()
	with HTMLtemplate(template_config['archive_template']) as temp:
		temp.set_insert('<!--message-->')
		temp.p("Here's all my posts from newest to oldest:")
		temp.set_insert('<!--results-->')
		for post in posts:
			temp.li()
			temp.a('/?p=' + post['url_title'], post['title'])
			temp.p(post['description'])
			temp.jump()

def serve_search_archive(search_string):
	"""
	Prints a list of links to post that match a user-submitted search string.
	"""
	sql = SQLcon(sql_config)
	posts = sql.execute('search_db', search_string)
	if posts is None:
		serve_error('500 Internal Error', 'Something went wrong. Please Try again later')
		return
	print_headers()
	result_message_flag = sum([post['rank'] for post in posts])
	with HTMLtemplate(template_config['archive_template']) as temp:
		temp.set_insert('<!--message-->')
		temp.p('Here are the results of your search:' if result_message_flag else 'There weren\'t any relevant posts with your search terms.')
		if result_message_flag:
			temp.set_insert('<!--results-->')
			for post in posts:
				if post['rank'] != 0:
					temp.li()
					temp.a('/?p=' + post['url_title'], post['title'])
					temp.p(post['description'])
					temp.jump()

def serve_email_challenge(fail = False):
	"""
	Prints the default contact page.
	A user must type in a word randomly selected from a word list to get contact information.
	This function gets that word and presents it to the user.
	"""
	sql = SQLcon(sql_config)
	wordlist_path = template_config['wordlist']
	random.seed()
	with open(wordlist_path, 'r') as wordlist:
		wordlist.seek(random.randrange(os.path.getsize(wordlist_path)))
		for c in iter(lambda: wordlist.read(1), '\n'):
			if c == '':
				wordlist.seek(random.randrange(os.path.getsize(wordlist_path)))
		word = wordlist.readline()[:-1]	
	sql.execute('insert_challenge', word, commit = True)	
	print_headers()
	with HTMLtemplate(template_config['email_challenge']) as temp:
		temp.set_insert('<!--message-->')
		if not fail:
			temp.p("Hi! Thanks for showing interest in contacting me! Unfortunately, the internet is full of spammers, and I don't want my inbox to fall prey to them by directly putting my email on this page, so I created a small 'challenge' that most web crawlers probably won't be able to get past. Just type in the word you see below into the grey box and hit 'Enter', then you should see my email.")
		else:
			temp.p("Sorry, that word wasn't typed in correctly. Please try again.")
		temp.set_insert('<!--word-->')
		temp.append_raw(word)

def check_email_challenge(challenge_string):
	"""
	Checks if the word generated in serve_email_challenge() is valid.
	If it is, print contact info.
	If not, call serve_email_challenge() again.
	"""
	sql = SQLcon(sql_config)
	res = sql.execute('find_challenge', challenge_string)
	if res is None:
		serve_email_challenge(fail = True)
		return	
	sql.execute('delete_challenge', res['challenge_id'], commit = True)
	print_headers()
	with HTMLtemplate(template_config['email_success']) as temp:	
		temp.set_insert('<!--message-->')
		temp.p('Thank you! My email is below. I hope to hear from you soon!')

def serve_error(http_status, message):
	"""
	Prints an error page with http_status and message.
	"""
	http_status_header = 'Status: ' + http_status
	print_headers(headers = [http_status_header])
	with HTMLtemplate(template_config['post_template']) as temp:
		temp.set_insert('<!--post-->')
		temp.h(http_status)
		temp.p(message)

if __name__ == '__main__':
	# only uncomment the line below if you're testing this application out
	# if you're going to run this on the internet, leave this line commented
	#cgitb.enable()
	handle_request()
