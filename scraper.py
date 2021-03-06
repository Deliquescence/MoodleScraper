#!/usr/bin/env python3
from bs4 import BeautifulSoup
import os
import sys
import requests
import itertools
import re
import urllib.request
import urllib.parse
import urllib.error
import configparser
import datetime

# read config
if not os.path.isfile('scraper.conf'):
    print("ERROR: Config not found! Copy `scraper.conf.sample` to `scraper.conf` and edit.")
    sys.exit()

config = configparser.RawConfigParser()
config.read('scraper.conf')

username = config.get("scraper", "user")
password = config.get("scraper", "pwd")
root = config.get("scraper", "root")
baseurl = config.get("scraper", "baseurl")

sections = itertools.count()
files = itertools.count()


class colors:
    HEADER = '\033[95m'
    OKBLUE = '\033[94m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'


def encode_path(path):
    return urllib.request.url2pathname(path.replace(':', '-').replace('"', ''))


def login(user, pwd):
    # Get login token
    TOKEN_REGEX = r"<input type=\"hidden\" name=\"logintoken\" value=\"(.*)\">"

    session = requests.Session()
    r = session.get(baseurl + 'login/index.php')
    match = re.search(TOKEN_REGEX, r.text)
    if match is None:
        print("ERROR: Couldn't find login token! (Did the regex break?)")
        sys.exit()

    token = match[1]
    authdata = {
        'logintoken': token,
        'username': user,
        'password': pwd
    }

    _r = session.post(baseurl + 'login/index.php', data=authdata)
    return session


def getSemesters(ses):
    r = ses.get(baseurl + 'my/')

    if(r.status_code != 200):
        print('ERROR: ' + str(r.status) + ' ' + r.reason)
        sys.exit()

    sem_ids = re.findall(r'catbox(\d+)', r.text)
    if not sem_ids:
        print("ERROR: Couldn't find any semesters! (Did the regex break?)")
        sys.exit()

    soup = BeautifulSoup(r.text, 'html.parser')
    semesters = dict()
    for id in sem_ids:
        sem_header = soup.find(id=f'catbox{id}').find_next("h3")
        # Trim "Click to show" after " - "
        sem_name = sem_header.text.split(" - ")[0]
        semesters[id] = sem_name

    return semesters


def getInfo(tag):
    c = dict()
    c['url'] = tag['href']
    p = str(tag.string).split(',')
    if len(p) >= 3:
        q = p[0].split('.')
        c['course'] = q[0].strip()
        c['sem'] = q[1]
        c['key'] = q[2].strip()
        c['name'] = p[1].strip()
    elif len(p) == 1:
        c['course'] = p[0].strip()
        c['sem'] = 'X'
        c['key'] = p[0].strip()
        c['name'] = p[0].strip()
    return c


def getCoursesForSemester(session, semester_id):
    r = session.get(
        baseurl + 'blocks/course_overview/partial.php?categories=' + semester_id)

    if(r.status_code != 200):
        print('ERROR: ' + str(r.status) + ' ' + r.reason)
        sys.exit()

    soup = BeautifulSoup(r.text, 'html.parser')
    courses = list()
    for o in soup.find_all('h2'):
        if (len(o.find_all('a')) > 0):
            c = getInfo(o.contents[0])
            courses.append(c)
    return courses


def saveFile(session, src, path, name):
    global files
    next(files)
    dst = path + name
    dst = dst.replace(':', '-').replace('"', '')

    if os.path.exists(dst):
        print('['+colors.OKBLUE+'skip'+colors.ENDC+'] |  |  +--%s' % name)
        return

    try:
        with open(dst, 'wb') as handle:
            print('['+colors.OKGREEN+'save'+colors.ENDC+'] |  |  +--%s' % name)
            r = session.get(src, stream=True)
            for block in r.iter_content(1024):
                if not block:
                    break
                handle.write(block)
    except IOError:
        print("Error: couldn't save file %s" % name)


def saveLink(session, url, path, name):
    global files
    next(files)
    fname = name.encode('utf-8').replace('/', '') + '.html'
    dst = path.encode('utf-8') + fname
    dst = dst.replace(':', '-').replace('"', '')
    try:
        with open(dst):
            print('['+colors.OKBLUE+'skip'+colors.ENDC+'] |  |  +--%s' % name)
            pass
    except IOError:
        with open(dst, 'wb') as handle:
            print('['+colors.OKGREEN+'save'+colors.ENDC+'] |  |  +--%s' % name)
            r = session.get(url)
            soup = BeautifulSoup(r.text, 'html.parser')
            link = soup.find(class_='region-content').a['href']
            try:
                handle.write('<a href="' + link.decode('utf-8') +
                             '">' + name.decode('utf-8') + '</a>')
            except UnicodeEncodeError:
                os.remove(dst)
                print('['+colors.FAIL+'fail'+colors.ENDC+'] |  |  +--%s' % name)
                pass


def saveInfo(path, info, tab):
    if "Foren" not in info:
        global files
        next(files)
        name = 'info.txt'
        dst = path + name
        dst = dst.replace(':', '-').replace('"', '')
        try:
            with open(dst):
                print('['+colors.OKBLUE+'skip'+colors.ENDC+'] ' +
                      tab + '+--%s' % name)
                pass
        except IOError:
            with open(dst, 'wb') as handle:
                print('['+colors.OKGREEN+'save'+colors.ENDC+'] ' +
                      tab + '+--%s' % name)
                handle.write(info.encode('utf-8'))


def downloadResource(session, res, path):
    try:
        src = res.a['href']
    except TypeError:
        return
    r = session.get(src)
    if(r.status_code == 200):
        headers = list(r.headers.keys())
        if ('Content-Disposition' in headers):
            # got a direct file link
            name = r.headers['Content-Disposition'].split(';')[1].split('=')[
                1].strip('"')
        else:
            # got a preview page
            soup = BeautifulSoup(r.text, 'html.parser')
            if ('content-type' in headers) and ('content-script-type' in headers) and ('content-style-type' in headers):
                # it's most obviously a website, which displays a download link
                src = soup.find(class_='region-content').a['href']
            else:
                # it's obviously an ugly frameset site
                src = soup.find_all('frame')[1]['src']
            name = os.path.basename(src)
        name = encode_path(name)
        saveFile(session, src, path, name)
    else:
        print('ERROR: ' + str(r.status) + ' ' + r.reason)
        sys.exit()


def downloadSection(session, s, path):
    # print "download Section"
    global sections
    if s['id'] == 'section-0':
        try:
            info = s.find(class_='activity label modtype_label').get_text()
        except AttributeError:
            pass
        else:
            saveInfo(path, info, '')

    else:
        next(sections)
        s = s.find(class_='content')
        name = s.find(class_='sectionname').text
        info = ''
        info = s.find(class_='summary').get_text().strip()
        if len(info) > 0:
            if 'Thema' in name:
                # prof failed to add a proper section name <.<
                temp = info.split('\n')
                name = temp.pop(0).strip().strip(':').replace('/', '-')
                info = "\n".join(temp)
        root = path
        path = root + name + '/'
        path = path.replace(':', '-').replace('"', '')
        if not os.path.exists(path):
            try:
                os.makedirs(path)
            except OSError:
                # filename too long
                name = name[:60]
                path = root + name + '/'
                path = path.replace(':', '-').replace('"', '')
                if not os.path.exists(path):
                    os.makedirs(path)
        print('       |  +--' + colors.BOLD + name + colors.ENDC)

        if len(info) > 0:
            saveInfo(path, info, '|  ')

    res = s.find_all(class_='activity resource modtype_resource')
    for r in res:
        downloadResource(session, r, path)
    folders = s.find_all(class_='activity folder modtype_folder')
    root = path
    for f in folders:
        downloadFolder(session, f, root)

    """
    links = s.find_all(class_='activity url modtype_url')
    for l in links:
        ln = l.find(class_='instancename')
        ln.span.extract()
        saveLink(session, l.a['href'], path, ln.get_text())
    """

    # remove empty folders
    if os.listdir(path) == []:
        os.rmdir(path)


def downloadFolder(session, folder_link_item, root):
    label = folder_link_item.find('span', class_='instancename').text

    path = root + label.replace('/', '-') + '/'
    path = encode_path(path)

    if not os.path.exists(path):
        os.makedirs(path)
    print('       |  +--' + colors.BOLD + label + colors.ENDC)

    # Navigate to actual folder page
    r = session.get(folder_link_item.find('a')['href'])

    soup = BeautifulSoup(r.text, 'html.parser')
    folder_contents = soup.find_all("span", class_='fp-filename-icon')

    for item in folder_contents:
        item_link = item.find('a')
        item_name = item.find('span', class_='fp-filename').contents[0]
        item_name = encode_path(item_name)

        saveFile(session, item_link['href'], path, item_name)


def downloadCourse(session, c, sem):
    global files
    global sections
    files = itertools.count()
    sections = itertools.count()
    name = c['key'].replace('/', '-') + '/'
    path = root + sem.replace('/', '-') + '/' + name
    path = encode_path(path)

    if not os.path.exists(path):
        os.makedirs(path)
    print('       +--' + colors.BOLD + name + colors.ENDC)
    r = session.get(c['url'])
    if(r.status_code == 200):
        soup = BeautifulSoup(r.text, 'html.parser')
        if not os.path.exists(path + '.dump'):
            os.makedirs(path + '.dump')

        dst = path + '.dump/' + \
            c['key'].replace('/', '-') + '-' + \
            str(datetime.date.today()) + '-full.html'
        dst = dst.replace(':', '-').replace('"', '')

        with open(dst, 'wb') as f:
            f.write(soup.encode('utf-8'))
        for s in soup.find_all(class_='section main clearfix'):
            downloadSection(session, s, path)
        # print 'Saved ' + str(files.next()) + ' Files in ' + str(sections.next()) + ' Sections'
    else:
        print('ERROR: ' + str(r.status) + ' ' + r.reason)
        sys.exit()


print(colors.HEADER)
print(r"      _____                    .___.__              ")
print(r"     /     \   ____   ____   __| _/|  |   ____      ")
print(r"    /  \ /  \ /  _ \ /  _ \ / __ | |  | _/ __ \     ")
print(r"   /    Y    (  <_> |  <_> ) /_/ | |  |_\  ___/     ")
print(r"   \____|__  /\____/ \____/\____ | |____/\___  >    ")
print(r"           \/                   \/           \/     ")
print(r"  _________                                         ")
print(r" /   _____/ ________________  ______   ___________  ")
print(r" \_____  \_/ ___\_  __ \__  \ \____ \_/ __ \_  __ \ ")
print(r" /        \  \___|  | \// __ \|  |_> >  ___/|  | \/ ")
print(r"/_______  /\___  >__|  (____  /   __/ \___  >__|    ")
print(r"        \/     \/           \/|__|        \/        ")
print(colors.ENDC)

# logging in
print("logging in...")
session = login(username, password)

# get semesters
print("getting Semesters...")
sems = getSemesters(session)
if not sems:
    print(colors.FAIL + 'No semester found - Quitting!' + colors.ENDC)
    sys.exit()
else:
    print(colors.WARNING + 'Available semester:' + colors.ENDC)
    for s in sorted(sems):
        print('[' + s + ']: ' + sems[s])

# input loop
ok = False
while not ok:
    s = input(colors.WARNING + 'Select semester: ' + colors.ENDC)
    ok = s in list(sems.keys())

# get courses
print("getting Courses...")
courses = getCoursesForSemester(session, s)
if not courses:
    print(colors.FAIL + 'No courses in this semester - Quitting!' + colors.ENDC)
    sys.exit()
else:
    print(colors.WARNING + 'Available courses:' + colors.ENDC)
    for c in courses:
        print('[' + str(courses.index(c)) + ']: ' + c['key'] + '.' +
              str(c['sem']) + ': ' + c['name'])

# confirmation
c = input(colors.WARNING +
          'Choose number of course to download, (a) for all or (q) to quit: ' + colors.ENDC)
if c == 'a':
    for f in courses:
        try:
            downloadCourse(session, f, sems[s])
            print(colors.WARNING + 'Successfully processed ' + str(next(files)) +
                  ' Files in ' + str(next(sections)) + ' Sections!' + colors.ENDC)
        except:
            print("Error while processing!")
    quit()

if c == 'q':
    print(colors.FAIL + 'Oh no? - Quitting!' + colors.ENDC)
    quit()

downloadCourse(session, courses.pop(int(c)), sems[s])
print(colors.WARNING + 'Successfully processed ' + str(next(files)) +
      ' Files in ' + str(next(sections)) + ' Sections!' + colors.ENDC)
