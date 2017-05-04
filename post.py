#!/usr/bin/env python3
# LightBlog: a lightweight Python blogging application.
# Copyright (C) 2017  Dylan Spriggs
# 
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
# 
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
# 
# You should have received a copy of the GNU General Public License along
# with this program; if not, write to the Free Software Foundation, Inc.,
# 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.
import re
import sys
import mysql.connector

help_str = """
To create a new post:				
	./post -i -title <title> -url <url title> -desc <description> -f <mml file>

To update a currently existing post:
	./post -u <url> [-title <title>] [-url <url>] [-date <YYYY-MM-DD>] [-desc <description>] [-text <mml file>]

To print an mml file converted to html to stdout:
	./post -p <mml file>

To print this help text:
	./post -h
"""

sql_config = {
	'unix_socket' : '/var/run/mysqld/mysqld.sock',
	'user' : 'writer',
	'password' : 'defwriterpw',
	'database' : 'blog',
	'raise_on_warnings' : True
}

def sanitize(line):
	"""
	Escape HTML characters like '<'.
	Also convert tab to four spaces so that tabs look the same to everyone.
	"""
	line = line.replace('&', '&amp;')
	line = line.replace('<', '&lt;')
	line = line.replace('>', '&gt;')
	line = line.replace('"', '&quot;')
	line = line.replace("'", '&#39;')
	line = line.replace("\t", '    ')
	return line

def convert_inline(line):
	"""
	Convert a line with {l}, {im}, {i}, {b}, {ic} elements into HTML elements.
	"""
	link_re = re.search('{l\|([^{}]+)}([^{}]+){l}', line)
	img_re = re.search('{im\|([^{}]+)}([^{}]+){im}', line)
	if link_re:
		line = re.sub(link_re.re, 
					  lambda x: ''.join(['<a href="', x.group(1), '">', x.group(2), '</a>']),
					  line)
	if img_re:
		line = re.sub(img_re.re, 
					  lambda x: ''.join(['<img src="', x.group(1), '" alt="', x.group(2), '" />']),
					  line)
	for tag in ('i', 'b', 'ic'):
		match = re.search('{' + tag + '}([^{}]+){' + tag + '}', line)
		if match:
			if tag == 'ic':
				line = re.sub(match.re, 
							  lambda x: ''.join(['<span class="inline-code">', x.group(1), '</span>']), 
							  line)
			else:
				line = re.sub(match.re, 
							  lambda x: ''.join(['<', tag, '>', x.group(1), '</', tag, '>']), 
							  line)
	return line

def convert_block(file_handler, close_tag = None, inline = False, enclose = None):
	"""
	Convert a block level element ({p}, {c}, {h}, {l}) into HTML.
	"""
	out_html = str()
	if close_tag is not None:
		found_close_tag = False
		for line in file_handler:
			if re.match('^' + close_tag + '$', line):
				found_close_tag = True
				break
			if inline:
				line = sanitize(line)
				if enclose is None:
					out_html += convert_inline(line)
				else: 
					out_html += ''.join(['<', enclose, '>', convert_inline(line)[:-1], '</', enclose, '>\n'])
			else:
				line = sanitize(line)
				out_html += line
		if not found_close_tag:
			print("Could not find corresponding close tag to " + close_tag, file = sys.stderr)
			file_handler.close()
			exit(1)
		return out_html
	else:
		for line in file_handler:
			if re.match('{p}', line):
				out_html += '<p>\n'
				out_html += convert_block(file_handler, close_tag = '{p}', inline = True)
				out_html += '</p>\n'
			elif re.match('{c}', line):
				out_html += '<div class="code"><code><pre class="code-font">\n'
				out_html += convert_block(file_handler, close_tag = '{c}')
				out_html += '</pre></code></div>\n'
			elif re.match('{h}', line):
				out_html += '<h3>\n'
				out_html += convert_block(file_handler, close_tag = '{h}')
				out_html += '</h3>\n'
			elif re.match('{l}', line):
				out_html += '<ul>\n'
				out_html += convert_block(file_handler, close_tag = '{l}', inline = True, enclose = 'li')
				out_html += '</ul>\n'
		return out_html

def setup_and_execute(query, *parameters, commit = False):
	"""
	setup and execute SQL query with optional paraments.
	Call with commit = True to alter data.
	"""
	try:
		con = mysql.connector.connect(**sql_config)
		cur = con.cursor(prepared = True)
		cur.execute(query, parameters)
		if not commit:
			return cur.fetchone()
		else:
			con.commit()
			return
	except mysql.connector.Error as e:
		print("SQL Error: {}".format(e), file = sys.stderr)
		sys.exit(1)
	finally:
		con.close()

if __name__ == '__main__':
	# create a new post. 
	if '-i' in sys.argv:
		try:
			title = sanitize(sys.argv[sys.argv.index('-title') + 1])
			url = sanitize(sys.argv[sys.argv.index('-url') + 1])
			desc = sanitize(sys.argv[sys.argv.index('-desc') + 1])
			mml = sys.argv[sys.argv.index('-f') + 1]
			with open(mml, 'r') as fh:
				text = convert_block(fh)
			setup_and_execute("INSERT INTO blog_posts(title, url_title, post_date, description, text) VALUES(%s,%s,CURDATE(),%s,%s);", title, url, desc,text, commit = True)
		except (ValueError, IndexError) as e:
			if isinstance(e, ValueError):	
				print(e, file = sys.stderr)
				print("A field was omitted", file = sys.stderr)
				sys.exit(1)
			elif isinstance(e, IndexError):
				print("A field was not populated", file = sys.stderr)
				sys.exit(1)
	# update a post with new information
	elif '-u' in sys.argv:
		try:
			url = sys.argv[sys.argv.index('-u') + 1]
			post_id = setup_and_execute("SELECT post_id FROM blog_posts WHERE url_title = %s;", url)
			if post_id is None:
				print("A post with that url title does not exist.", file = sys.stderr)
				sys.exit(1)
			post_id = post_id[0]
		except IndexError:
			print("No url title provided", file = sys.stderr)
			exit(1)
		try:
			fields = {
				"-title" : "UPDATE blog_posts SET title = %s WHERE post_id = %s;",
				"-url"   : "UPDATE blog_posts SET url_title = %s WHERE post_id = %s;",
				"-date"  : "UPDATE blog_posts SET post_date = %s WHERE post_id = %s;",
				"-desc"  : "UPDATE blog_posts SET description = %s WHERE post_id = %s;",
				"-text"  : "UPDATE blog_posts SET text = %s WHERE post_id = %s;"
			}
			for field in fields.keys():
				if field in sys.argv:
					if field == '-text':
						with open(sys.argv[sys.argv.index(field) + 1], 'r') as fh:
							setup_and_execute(fields[field], convert_block(fh), post_id, commit = True)
					else:
						setup_and_execute(fields[field], sanitize(sys.argv[sys.argv.index(field) + 1]), post_id, commit = True)
		except IndexError:
			print("A field was not populated", file = sys.stderr)
			exit(1)
	# print a converted mml file to stdout
	elif '-p' in sys.argv:
		try:
			with open(sys.argv[sys.argv.index('-p') + 1], 'r') as fh:
				print(convert_block(fh))
		except IndexError:
			print("No input file provided", file = sys.stderr)
			exit(1)
	# print help string
	elif '-h' in sys.argv:
		print(help_str)
	# error otherwise.
	else:
		print("No operation specified. Be sure to use either -i to insert, -u to update, or -p to print. See post -h for more info", file = sys.stderr)
