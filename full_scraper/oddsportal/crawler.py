"""
crawler.py

Logic for the overall Odds Portal scraping utility focused on crawling

"""


from .models import Season
from pyquery import PyQuery as pyquery
from selenium import webdriver
from selenium.common.exceptions import NoSuchElementException
from selenium.common.exceptions import WebDriverException
from selenium.webdriver.common.by import By  # Add this import at the top
# Create Chrome service
from selenium.webdriver.chrome.service import Service

import logging
import time


logger = logging.getLogger(__name__)


class Crawler(object):
    """
    A class to crawl links from oddsportal.com website.
    Makes use of Selenium and BeautifulSoup modules.
    """
    WAIT_TIME = 3  # max waiting time for a page to load
    
    def __init__(self, wait_on_page_load=3):
        """
        Constructor
        """
        self.base_url = 'https://www.oddsportal.com'
        self.wait_on_page_load = wait_on_page_load if wait_on_page_load is not None else 3
        
        # Setup Chrome options with additional arguments
        self.options = webdriver.ChromeOptions()
        self.options.add_argument('--headless')
        self.options.add_argument('--disable-gpu')
        self.options.add_argument('--no-sandbox')
        self.options.add_argument('--disable-dev-shm-usage')
        self.options.add_argument('--window-size=1920,1080')
        self.options.add_argument('--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')
        
        service = Service('./chromedriver/chromedriver.exe')
        
        # Initialize the driver with the new syntax
        self.driver = webdriver.Chrome(service=service, options=self.options)
        logger.info('Chrome browser opened in headless mode')

    def go_to_link(self, link):
        """
        returns True if no error
        False when page not found
        """
        try:
            self.driver.get(link)
            # Wait for page to load
            time.sleep(self.wait_on_page_load)
            
            # Try multiple selectors since the site might have different versions
            selectors = [
                '.button-dark',
                'button[data-login]',
                'a[href*="login"]',
                '#login-button',
                'div[class*="main"]',  # Main content areas
                'div[class*="content"]',
                'nav',  # Navigation elements
                'header',
                'table',  # Results tables
                'div[class*="odds"]'  # Odds-related content
            ]
            
            for selector in selectors:
                try:
                    self.driver.find_element(By.CSS_SELECTOR, selector)
                    return True
                except NoSuchElementException:
                    continue
                    
            logger.warning(f"No login button found using any selector - {link}")
            return False
            
        except Exception as e:
            logger.warning(f"Error accessing link {link}: {str(e)}")
            return False
        
    def get_html_source(self):
        return self.driver.page_source
    
    def close_browser(self):
        time.sleep(5)
        try:
            self.driver.quit()
            logger.info('Browser closed')
        except WebDriverException:
            logger.warning('WebDriverException on closing browser - maybe closed?')

    def get_seasons_for_league(self, main_league_results_url):
        """
        Params:
            (str) main_league_results_url e.g. https://www.oddsportal.com/hockey/usa/nhl/results/

        Returns:
            (list) urls to each season for given league
        """
        seasons = []
        logger.info('Getting all seasons for league via %s', main_league_results_url)
        if not self.go_to_link(main_league_results_url):
            logger.error('League results URL loaded unsuccessfully %s', main_league_results_url)
            return seasons

        html_source = self.get_html_source()
        
        # Save HTML for debugging
        try:
            with open('page_source.html', 'w', encoding='utf-8') as f:
                f.write(html_source)
            logger.info("Saved page source to page_source.html")
        except Exception as e:
            logger.error(f"Failed to save page source: {str(e)}")

        html_querying = pyquery(html_source)
        
        # Try multiple potential selectors for season links
        selectors = [
            'a[href*="/results/"]',  # Links containing /results/
            'div[class*="seasons"] a',  # Links within seasons div
            'div[class*="filter"] a',  # Links within filter div
            'div[class*="tournament-nav"] a'  # Links within tournament navigation
        ]
        
        for selector in selectors:
            season_links = html_querying.find(selector)
            if season_links:
                logger.info(f'Found {len(season_links)} season links with selector: {selector}')
                
                for season_link in season_links:
                    href = season_link.attrib['href']
                    text = season_link.text or ''
                    
                    # Only process links that look like season links
                    if '/results/' in href and text:
                        this_season = Season(text.strip())
                        this_season_url = href
                        this_season.urls.append(this_season_url)
                        seasons.append(this_season)
                        logger.info(f'Added season: {text.strip()} - {href}')

        if not seasons:
            logger.warning('No season links found - try checking the HTML structure')
            
        return seasons
    
    def fill_in_season_pagination_links(self, season):
        """
        Params:
            (Season) object with just one entry in its urls field, to be modified
        """
        first_url_in_season = season.urls[0]
        self.go_to_link(first_url_in_season)
        html_source = self.get_html_source()
        html_querying = pyquery(html_source)
        # Check if the page says "No data available"
        no_data_div = html_querying.find('div.message-info > ul > li > div.cms')
        if no_data_div != None and no_data_div.text() == 'No data available':
            # Yes, found "No data available"
            logger.warning('Found "No data available", skipping %s', first_url_in_season)
            return
        # Just need to locate the final pagination tag
        pagination_links = html_querying.find('div#pagination > a')
        # It's possible, however, there is no pagination...
        if len(pagination_links) <= 1:
            return
        last_page_number = -1
        last_page_url = None
        for link in reversed(pagination_links):
            span = link.find('span')
            if span != None and span.text != None and '»|' in span.text:
                # This is the last link because it has these two characters in it...
                last_page_number = int(link.attrib['x-page'])
                last_page_url = first_url_in_season + link.attrib['href']
                break
        # If the last page number was set, the page format must've changed - RuntimeError
        if last_page_number == -1:
            logger.error('Could not locate final page URL from %s', first_url_in_season)
            raise RuntimeError('Could not locate final page URL from %s', first_url_in_season)
        for i in range(2,last_page_number):
            this_url = last_page_url.replace('page/' + str(last_page_number), 'page/' + str(i))
            season.urls.append(this_url)
        season.urls.append(last_page_url)
