"""
Install multipath-tcp kernel from github releases
"""
import configparser
import logging
import os
from pathlib import Path
import re
import subprocess
#-
from bs4 import BeautifulSoup
import requests
from requests.adapters import HTTPAdapter, Retry
from yarl import URL

ROOT_DIR = Path(os.environ['ROOT_DIR'])
BASEURL = URL('https://github.com/multipath-tcp/mptcp/releases')
VERSION_PAT = re.compile(r'(?P<ver>v\d+\.\d+(\.\d+)?)$')
KERNEL_VERSION_PAT = re.compile(r'linux-image-(?P<ver>[\d.]+)\.mptcp')
PROGRESS_FILE = ROOT_DIR / 'progress.ini'

logging.basicConfig(level=logging.INFO)
_logger = logging.getLogger(__name__)
_progress = configparser.ConfigParser()

def create_http_client():
    """Create requests retrying Session
    """
    retries = Retry(total=3, backoff_factor=1,
            status_forcelist=[500, 502, 503, 504, 521],
            allowed_methods=['POST'])
    session = requests.Session()
    session.mount('https://', HTTPAdapter(max_retries=retries))
    return session


def save_progress():
    """Persist config
    """
    with open(PROGRESS_FILE, 'w', encoding='utf-8') as fw:
        _progress.write(fw)


def update_grub(kernel_version):
    """Update grub to select latest mptcp kernel
    """
    index = 0
    with open('/boot/grub/grub.cfg', 'r', encoding='utf-8') as fr:
        content = fr.read()
    for line in content.splitlines():
        if not re.search(r'^\s+menuentry\s', line):
            continue
        index += 1
        if not 'mptcp-advanced' in line:
            continue
        if not f'{kernel_version}.mptcp' in line:
            continue

        # ToDo: Must add GRUB_DISABLE_SUBMENU=y
        subprocess.check_call(['sed', '-i',
                fr'/GRUB_DEFAULT\s*=/s/=[a-z0-9">]*$/=saved/',
                '/etc/default/grub'])
        subprocess.check_call(['update-grub'])
        subprocess.check_call(['grub-set-default',
                line.split()[-2].strip("'")])
        break


def main():
    #update_grub('5.4.230')
    #return 0

    if PROGRESS_FILE.exists():
        _progress.read(PROGRESS_FILE)
    for section in ('Files', 'General'):
        try:
            _progress.add_section(section)
        except configparser.DuplicateSectionError:
            continue

    with create_http_client() as ua:
        res = ua.get(BASEURL)
        if not res.ok:
            print((res.status_code, res.content))
            return 1

    soup = BeautifulSoup(res.content, 'html.parser')
    for el_h2 in soup.find_all('h2'):
        match = VERSION_PAT.search(el_h2.text)
        if not match:
            continue
        latest_version = match.group('ver')
        el_pre = el_h2.parent.find('pre')
        lines = [x for x in el_pre.text.splitlines() if x.endswith('.deb')]
        files = [x.split()[-1].strip() for x in lines]
        break
    else:
        _logger.error("ERROR: please update crawler")
        return 1

    try:
        last_version = _progress.get('General', 'version')
    except configparser.NoOptionError:
        last_version = None
    if last_version == latest_version:
        return 0

    try:
        old_versions = _progress.get('General', 'deprecated_versions')
        old_versions = old_versions.split(';')
    except configparser.NoOptionError:
        old_versions = []

    downloads = []

    destdir = ROOT_DIR / 'var' / 'download' / latest_version
    os.makedirs(destdir, exist_ok=True)
    for filename in files:
        try:
            if filename.startswith('linux-headers'):
                if _progress.get('Files', 'linux-headers') == filename:
                    _logger.info("Not downloading %s", filename)
                    downloads.append(destdir / filename)
                    continue
            elif filename.startswith('linux-image'):
                if '-dbg' in filename:
                    continue
                match = KERNEL_VERSION_PAT.search(filename)
                if not match:
                    _logger.error("Didn't know how to get kenrel version from %s",
                            filename)
                    return 1
                kernel_version = match.group('ver')
                if _progress.get('Files', 'linux-image') == filename:
                    _logger.info("Not downloading %s", filename)
                    downloads.append(destdir / filename)
                    continue
            elif filename.startswith('linux-libc-dev'):
                if _progress.get('Files', 'linux-libc-dev') == filename:
                    _logger.info("Not downloading %s", filename)
                    downloads.append(destdir / filename)
                    continue
            elif filename.startswith('linux-mptcp'):
                if _progress.get('Files', 'linux-mptcp') == filename:
                    _logger.info("Not downloading %s", filename)
                    downloads.append(destdir / filename)
                    continue
            else:
                _logger.error("Unknown file: %s", filename)
                return 1
        except configparser.NoOptionError:
            pass

        _logger.info("Downloading %s...", filename)
        url = BASEURL / 'download' / latest_version / filename
        with create_http_client() as ua:
            with ua.get(url, stream=True) as res:
                res.raise_for_status()
                with open(destdir / filename, 'wb') as fw:
                    for chunk in res.iter_content(chunk_size=8192):
                        fw.write(chunk)
        _logger.info("Downloaded %s", filename)
        downloads.append(destdir / filename)

        if filename.startswith('linux-headers'):
            _progress.set('Files', 'linux-headers', filename)
        elif filename.startswith('linux-image'):
            _progress.set('Files', 'linux-image', filename)
        elif filename.startswith('linux-libc-dev'):
            _progress.set('Files', 'linux-libc-dev', filename)
        elif filename.startswith('linux-mptcp'):
            _progress.set('Files', 'linux-mptcp', filename)
        save_progress()

    for downloaded_file in downloads:
        subprocess.check_call(['dpkg', '-i', downloaded_file])

    update_grub(kernel_version)

    _progress.set('General', 'version', latest_version)
    _progress.set('General', 'kernel_version', kernel_version)
    if last_version:
        old_versions.append(last_version)
    _progress.set('General', 'deprecated_versions', ';'.join(old_versions))
    save_progress()

    return 0


if __name__ == '__main__':
    exit(main())
