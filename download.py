import os
import sys
import xml.etree.ElementTree as ET
from difflib import SequenceMatcher
from zipfile import ZipFile
import shutil
import stat

import requests

PLATFORM = "mac-x64"

### Consts used in the retrieval of the Chrome version number
CHROME_PLIST_PATH = "/Applications/Google Chrome.app/Contents/Info.plist"
XML_VERSION_KEY = "KSVersion"

DEBUG = False
LOG_INDENT = "  "


def parse_args() -> list[str]:
    """
    Parses the args passed to this file
    """
    dest_dir = os.getcwd()  # default

    args = sys.argv[1:]
    for arg in args:
        arg = arg.strip()
        lower = arg.lower()

        # dest_dir check
        if os.path.isdir(arg):
            dest_dir = arg

        # DEBUG check
        if lower in ["-d", "--debug"]:
            global DEBUG
            DEBUG = True

    return [dest_dir]


def get_chrome_version() -> str:
    """
    This function dynamically inspects the package contents of our Chrome
    application to grab the current version in the form of a string

    >>> get_chrome_version()
    "125.0.6422.113"
    """

    # - To get the version of our Chrome application, we can inspect its
    #   'Info.plist' file
    # - Upon visual inspection, it seems to be an XML file
    tree = ET.parse(CHROME_PLIST_PATH)

    # - I did a Ctrl+F of the current version value, and it's found in a few
    #   places
    # - The most accessible is probably the one which is in a <string> tag
    #   which has a corresponding <key> tag whose inner text is "KSVersion"
    # - These tags are within a <dict> tag which is the first child of the
    #   root of the XML tree
    root = tree.getroot()
    dict_tag = next(iter(root))

    # To find the target <key>, we just iterate over each child of 'dict_tag'
    # and check the inner text. If we find the one we want, we check the
    # inner text of the next tag - this will be the version string that we
    # want

    found_key = False
    for child in dict_tag:
        inner_text = child.text

        # If we're looking for the "KSVersion" <key> tag
        if not found_key:

            # We only care about <key> tags
            if child.tag != "key":
                continue

            if inner_text == XML_VERSION_KEY:
                # The next tag will contain the version data
                found_key = True

        # We're now inspecting the <string> tag which will contain the version
        # value. This means 'inner_text' will be the info we want
        else:

            if DEBUG:
                print(LOG_INDENT + "Found version value:", inner_text)

            return inner_text

    raise Exception("Didn't find version value for some reason :(")


def get_chromedriver_download_url(our_version: str) -> str:
    """
    Given the version of our Chrome download, this function gets the url of
    the chromedriver download

    Basically, we look for the download with the version number which is the
    most similar to our Chrome download's version number. Idk how robust
    this is, but it's all I could think of doing

    >>> get_chromedriver_download_url("125.0.6422.113")
    "https://storage.googleapis.com/chrome-for-testing-public/125.0.6422.3/mac-x64/chromedriver-mac-x64.zip"
    """

    ### Grab the json containing all the versions & download urls ###
    # I found this url by following the below URLs:
    # - https://developer.chrome.com/docs/chromedriver/downloads
    # - https://googlechromelabs.github.io/chrome-for-testing/
    # - https://github.com/GoogleChromeLabs/chrome-for-testing#json-api-endpoints
    json_url = "https://googlechromelabs.github.io/chrome-for-testing/known-good-versions-with-downloads.json"
    response = requests.get(json_url)

    # The base response json is a 'dict' with 'timestamp' and 'versions'
    # data. "versions" is a list of dicts; each has a "version" key, whose
    # accompanying value is a string (e.g. "113.0.5672.0").
    # Obviously we don't care about the timestamp...
    data = response.json()["versions"]

    ### Find which is the most similar to our version ###
    # Basically, the idea is to just manually compare the strings to see how
    # similar they are. The most similar version will be the one we go with

    # List of each version covered
    # e.g. ['127.0.6508.0', '127.0.6509.0', '127.0.6510.0', ...]
    version_numbers = (entry["version"] for entry in data)

    most_similar__ratio = None
    most_similar__index = None
    for index, version in enumerate(version_numbers):
        # Ref: https://stackoverflow.com/a/17388505
        similarity = SequenceMatcher(None, version, our_version).ratio()

        # If the most_similar__ variables are uninitialised
        condition1 = (most_similar__ratio is None) and (most_similar__index is None)

        # If the current similarity is better than the best recorded similarity
        # so far
        condition2 = (not condition1) and (similarity > most_similar__ratio)

        if condition1 or condition2:
            most_similar__ratio = similarity
            most_similar__index = index

    ### Get the data corresponding to the most similar version ###
    most_similar = data[most_similar__index]

    # There is a list of dicts representing chromedriver downloads. Each
    # varies depending on the platform (e.g. "mac-x64", "linux64", "win32").
    # Obviously the only one we care about is mac-x64, so we just grab that
    # data, and return the "url" property in the dict
    platforms = most_similar["downloads"]["chromedriver"]
    platform = next(entry for entry in platforms if entry["platform"] == PLATFORM)
    url = platform["url"]

    if DEBUG:
        print(LOG_INDENT + "Download URL:", url)

    return url


def download_chromedriver(url: str, dest_dir: str) -> str:
    """
    Given the download url for the specific chromedriver version, this
    function:

    - Downloads the zip file
    - Unzips it
    - Moves the 'chromedriver' executable in the resulting directory to
      the destination directory `dest_dir`
    - Removes the zip file and its resulting directory, including the
      LICENSE.chromedriver file within

    And returns the filepath of the `chromedriver` executable
    """
    ### Download the .zip file ###

    # Get the full path for the zip
    zip_name = "chromedriver.zip"
    zip_path = os.path.join(dest_dir, zip_name)

    # Cheers ChatGPT
    with requests.get(url, stream=True) as response:
        response.raise_for_status()
        with open(zip_path, "wb") as file:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:  # filter out keep-alive new chunks
                    file.write(chunk)

    if DEBUG:
        size = os.path.getsize(zip_path)
        print(
            LOG_INDENT + "Downloaded .zip file:",
            zip_path,
            "of size",
            size,
            "bytes",
        )

    ### Extract the .zip file ###
    with ZipFile(zip_path, "r") as zip_ref:
        zip_ref.extractall(dest_dir)

    # The previous operation creates a new directory called 'chromedriver-'
    # plus the platform name. It contains the chromedriver executable, as
    # well as a LICENSE.chromedriver file
    unzipped_dir = os.path.join(dest_dir, "chromedriver-" + PLATFORM)

    ### Move 'chromedriver' to the root of the project ###
    chromedriver_src_path = os.path.join(unzipped_dir, "chromedriver")
    chromedriver_dest_path = os.path.abspath(
        os.path.join(dest_dir, "chromedriver"),
    )
    shutil.move(chromedriver_src_path, chromedriver_dest_path)

    ### Clean up .zip and the unzipped directory ###
    os.remove(zip_path)
    shutil.rmtree(unzipped_dir)

    return chromedriver_dest_path


def amend_permission(dest_dir: str) -> None:
    """
    Given the parent directory (`dest_dir`) of the `chromedriver` executable,
    this function changes the permissions to allow it to be executable.

    It's the equivalent of entering this command into the terminal:
    `chmod +x ./chromedriver`
    """
    # The path of the chromedriver executable
    path = os.path.join(dest_dir, "chromedriver")

    if DEBUG:
        permission_mask_before = oct(os.stat(path).st_mode)[-3:]

    # Change the permission of the file to be executable
    os.chmod(path, stat.S_IRWXU)

    if DEBUG:
        permission_mask_after = oct(os.stat(path).st_mode)[-3:]
        print(
            LOG_INDENT + "Permission for",
            path,
            "changed from",
            permission_mask_before,
            "to",
            permission_mask_after,
        )


def download(dest_dir: str) -> str:
    """
    Given the desired destination directory of the resulting `chromedriver`
    exexutable (`dest_dir`), which defaults to the root of this project,
    this function does the following:

    - Finds the current Chrome version - `get_chrome_version`
    - Gets the corresponding chromedriver download URL - `get_chromedriver_download_url`
    - Downloads the data at the URL - `download_chromedriver`
    - Amends the permissions so `chromedriver` can be used out-the-box - `amend_permission`

    And returns the path of the downloaded `chromedriver` executable
    """
    print("Getting chrome version...")
    version = get_chrome_version()
    print("Done!", os.linesep)

    print("Getting chromedriver download url...")
    url = get_chromedriver_download_url(version)
    print("Done!", os.linesep)

    print("Downloading chromedriver from url...")
    filepath = download_chromedriver(url, dest_dir)
    print("Done!", os.linesep)

    print("Amending chromedriver permissions...")
    amend_permission(dest_dir)
    print("Done!", os.linesep)

    print("Downloaded chromedriver to:")
    print(filepath)

    return filepath


def main() -> None:
    """
    If this file is executed, this function is called; basically the whole
    downloading process is carried out
    """

    args = parse_args()
    dest_dir = args[0]

    # Do the downloading
    download(dest_dir)


if __name__ == "__main__":
    main()
