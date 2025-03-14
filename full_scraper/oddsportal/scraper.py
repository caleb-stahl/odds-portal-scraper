"""
scraper.py

Logic for the overall Odds Portal scraping utility focused on scraping

"""


from .models import Game
from .models import Season
from pyquery import PyQuery as pyquery
from selenium import webdriver
from selenium.common.exceptions import NoSuchElementException
from selenium.common.exceptions import WebDriverException
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.by import By

import datetime
import logging
import os
import re
import time


logger = logging.getLogger(__name__)


class Scraper(object):
    """
    A class to scrape/parse match results from oddsportal.com website.
    Makes use of Selenium and BeautifulSoup modules.
    """
    
    def __init__(self, wait_on_page_load=3):
        """
        Constructor
        """
        self.base_url = 'https://www.oddsportal.com'
        self.wait_on_page_load = wait_on_page_load if wait_on_page_load is not None else 3
        
        # Setup Chrome options with additional arguments for stability
        self.options = webdriver.ChromeOptions()
        self.options.add_argument('--headless')
        self.options.add_argument('--disable-gpu')
        self.options.add_argument('--no-sandbox')
        self.options.add_argument('--disable-dev-shm-usage')
        self.options.add_argument('--dns-prefetch-disable')  # Disable DNS prefetching
        self.options.add_argument('--disable-extensions')    # Disable extensions
        self.options.add_argument('--proxy-server="direct://"')  # Direct connection
        self.options.add_argument('--proxy-bypass-list=*')      # Bypass proxy
        
        # Create service object with increased timeout
        from selenium.webdriver.chrome.service import Service
        service = Service(
            executable_path='./chromedriver/chromedriver.exe',
            service_args=['--verbose'],
            log_path='chromedriver.log'
        )
        
        try:
            # Initialize the driver with retry mechanism
            max_retries = 3
            for attempt in range(max_retries):
                try:
                    self.driver = webdriver.Chrome(
                        service=service,
                        options=self.options
                    )
                    logger.info('Chrome browser opened in headless mode')
                    break
                except Exception as e:
                    if attempt == max_retries - 1:
                        raise
                    logger.warning(f'Failed to initialize browser (attempt {attempt + 1}/{max_retries}): {str(e)}')
                    time.sleep(2)
                    
        except Exception as e:
            logger.error(f'Failed to initialize browser after {max_retries} attempts: {str(e)}')
            raise

    def go_to_link(self, link):
        """
        returns True if no error
        False when page not found
        """
        max_retries = 3
        for attempt in range(max_retries):
            try:
                self.driver.get(link)
                time.sleep(self.wait_on_page_load)
                
                # Try multiple selectors
                selectors = ['.button-dark', 'div[class*="main"]', 'table']
                for selector in selectors:
                    try:
                        self.driver.find_element(By.CSS_SELECTOR, selector)
                        return True
                    except NoSuchElementException:
                        continue
                
                logger.warning(f'No valid elements found on page - {link}')
                return False
                
            except WebDriverException as e:
                if 'ERR_NAME_NOT_RESOLVED' in str(e):
                    logger.warning(f'DNS resolution failed (attempt {attempt + 1}/{max_retries}): {link}')
                    time.sleep(5)  # Wait before retry
                    continue
                logger.error(f'WebDriver error: {str(e)}')
                return False
                
        logger.error(f'Failed to load page after {max_retries} attempts: {link}')
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

    def populate_games_into_season(self, season):
        """
        Scrapes games data including scores and odds from the season pages
        
        Args:
            season (Season): Season object to populate with games data
        """
        for url in season.urls:
            if not self.go_to_link(url):
                logger.warning(f'Failed to load page: {url}')
                continue
                
            html_source = self.get_html_source()
            html_querying = pyquery(html_source)
            
            # Debug: Save HTML for inspection
            try:
                with open('debug_page.html', 'w', encoding='utf-8') as f:
                    f.write(html_source)
                logger.debug(f"Saved page source to debug_page.html")
            except Exception as e:
                logger.error(f"Failed to save debug page: {str(e)}")

            # Find all game rows
            game_rows = html_querying('div[class*="eventRow"]')
            
            for row in game_rows:
                try:
                    game = Game()
                    row_query = pyquery(row)
                    #get the game specific url
                    game_link = row_query('a[href*="/american-football/"]').attr('href')
                    if game_link != "" and game_link is not None:
                        game.game_url = self.base_url + game_link + "#home-away;8"
                        print(game.game_url)
                        
                        if self.go_to_link(game.game_url):
                            game_html_source = self.get_html_source()
                            game_query = pyquery(game_html_source)
                            
                            try:
                                # Extract average odds with safer error handling
                                # avg_row = game_query('div:contains("Average") + div.border-black-borders')
                                # print("AVG ROW:      ", avg_row)
                                # if avg_row:
                                # Get home odds
                                home_odds_elem = game_query('p[class="height-content"]').items()
                                home_odds_elem = list(home_odds_elem)[-6:-3]
                                print(home_odds_elem)
                                if home_odds_elem:
                                    try:
                                        home_avg = float(home_odds_elem[0].text())
                                        game.odds_home = round((home_avg - 1) * 100) if home_avg >= 2.00 else round(-100 / (home_avg - 1))
                                    except (ValueError, ZeroDivisionError):
                                        logger.warning(f"Invalid home odds value: {home_odds_elem.text()}")
                                
                                # Get away odds
                                    try:
                                        away_avg = float(home_odds_elem[1].text())
                                        game.odds_away = round((away_avg - 1) * 100) if away_avg >= 2.00 else round(-100 / (away_avg - 1))
                                    except (ValueError, ZeroDivisionError):
                                        logger.warning(f"Invalid away odds value: {home_odds_elem.text()}")
                                
                                # Get draw odds if applicable
                                if season.possible_outcomes == 3:
                                    try:
                                        draw_avg = float(home_odds_elem[2].text())
                                        game.odds_draw = round((draw_avg - 1) * 100) if draw_avg >= 2.00 else round(-100 / (draw_avg - 1))
                                    except (ValueError, ZeroDivisionError):
                                        logger.warning(f"Invalid draw odds value: {home_odds_elem[2].text()}")
                            
                            except Exception as e:
                                logger.error(f"Error extracting odds for {game.game_url}: {str(e)}")


                    # Get teams
                    home_elem = row_query('p.participant-name:first')
                    away_elem = row_query('p.participant-name:last')
                    
                    if home_elem and away_elem:
                        game.team_home = home_elem.text().strip()
                        game.team_away = away_elem.text().strip()
                    
                    # Get scores
                    score_elem = row_query('div[class*="flex gap-1 font-bold"]')
                    if score_elem:
                        scores = score_elem.text().split('–')
                        if len(scores) == 2:
                            game.score_home = int(scores[0].strip())
                            game.score_away = int(scores[1].strip())
                    
                    
                    # Set metadata
                    game.retrieval_datetime = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
                    game.retrieval_url = url
                    game.num_possible_outcomes = season.possible_outcomes
                    
                    # Get initial odds from the main page
                    odds_elems = row_query('p[class*="height-content !text-black-main"]')
                    if odds_elems:
                        for i, odd_elem in enumerate(odds_elems):
                            odd_text = float(pyquery(odd_elem).text())
                            odd_text = round((odd_text - 1) * 100) if odd_text >= 2.00 else round(-100 / (odd_text - 1))
                            if i == 0:  # Home odds 
                                game.final_odds_home = odd_text
                            elif i == 1:  # Away odds
                                game.final_odds_away = odd_text
                            elif i == 2 and season.possible_outcomes == 3:  # Draw odds if applicable
                                game.final_odds_draw = odd_text
                    
                    # Determine outcome
                    if game.score_home is not None and game.score_away is not None:
                        if game.score_home > game.score_away:
                            game.outcome = 'HOME'
                        elif game.score_home < game.score_away:
                            game.outcome = 'AWAY'
                        else:
                            game.outcome = 'DRAW'        
                    
                    
                    if game_link != "" and game_link is not None:
                        game.game_url = self.base_url + game_link + "#home-away;1"
                        print(game.game_url)
                        
                        if self.go_to_link(game.game_url):
                            game_html_source = self.get_html_source()
                            game_query = pyquery(game_html_source)
                        try:
                            # Wait for the prediction tab and click it to ensure content loads
                            wait = WebDriverWait(self.driver, 10)

                            # Wait for the percentage to be non-zero
                            def check_percentage_loaded(driver):
                                elements = driver.find_elements(By.CSS_SELECTOR, 
                                    'div[class="height-content absolute w-full cursor-pointer text-center"]')
                                return any(elements) and any(e.text != '0%' for e in elements)
                            
                            wait.until(check_percentage_loaded)
                            
                            # Now get the updated percentage
                            percentage_elem = self.driver.find_element(By.CSS_SELECTOR, 
                                'div[class="height-content absolute w-full cursor-pointer text-center"]')
                            percentage_text = percentage_elem.text
                            if percentage_text and '%' in percentage_text:
                                game.pub_percent = float(percentage_text.strip('%'))
                                print(f"Found percentage: {game.pub_percent}%")
                        except Exception as e:
                            logger.warning(f"Failed to get public percentage: {str(e)}")
                    
                    print(game.team_home)
                    print(game.team_away)
                    print(game.outcome)
                    print(game.odds_away)
                    print(game.odds_home)
                    print(game.final_odds_away)
                    print(game.final_odds_home)
                    # Only add game if we have valid data
                    if game.team_home and game.team_away and game.odds_home and game.odds_away:
                        season.add_game(game)
                        logger.debug(f"Added game: {game.team_home} vs {game.team_away}")
                    
                except Exception as e:
                    logger.warning(f'Failed to parse game row: {str(e)}')
                    continue

            logger.info(f'Processed {len(season.games)} games from {url}')


if __name__ == '__main__':
    s = Scraper()
    s.go_to_link('https://www.oddsportal.com/basketball/usa/nba/results/#/page/2/')
    s.close_browser()
        