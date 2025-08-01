#!/usr/bin/env python3
"""
Watch Exchange Singapore Scraper

This script scrapes watch data from https://watchexchange.sg/watches/
with support for pagination and various output options.

Usage:
    python watch_scraper.py --all --output watches_all.json
    python watch_scraper.py --pages 1 5 --output watches_1_to_5.json
    python watch_scraper.py --page 1 --output watches_page_1.json
"""

import requests
from bs4 import BeautifulSoup
import json
import argparse
import time
import re
from datetime import datetime
from urllib.parse import urljoin, urlparse
import logging
from typing import Dict, List, Optional

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class WatchScraper:
    def __init__(self, base_url: str = "https://watchexchange.sg/watches/", delay: float = 1.0):
        """
        Initialize the scraper
        
        Args:
            base_url: Base URL for the watch listing
            delay: Delay between requests in seconds
        """
        self.base_url = base_url
        self.delay = delay
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Accept-Encoding': 'gzip, deflate',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
        })
    
    def get_page(self, url: str, retry_count: int = 3) -> Optional[BeautifulSoup]:
        """
        Fetch and parse a page with retry logic
        
        Args:
            url: URL to fetch
            retry_count: Number of retries
            
        Returns:
            BeautifulSoup object or None if failed
        """
        for attempt in range(retry_count):
            try:
                logger.info(f"Fetching: {url} (attempt {attempt + 1})")
                response = self.session.get(url, timeout=30)
                response.raise_for_status()
                return BeautifulSoup(response.content, 'html.parser')
            except requests.RequestException as e:
                logger.warning(f"Error fetching {url} (attempt {attempt + 1}): {e}")
                if attempt < retry_count - 1:
                    wait_time = (attempt + 1) * 2
                    logger.info(f"Retrying in {wait_time} seconds...")
                    time.sleep(wait_time)
                else:
                    logger.error(f"Failed to fetch {url} after {retry_count} attempts")
        return None
    
    def extract_main_brand_name(self, full_brand_text: str) -> str:
        """
        Extract main brand name from full brand + model text
        
        Args:
            full_brand_text: Full brand and model text (e.g., "Rolex Sky Dweller Oysterflex")
            
        Returns:
            Main brand name (e.g., "ROLEX")
        """
        if not full_brand_text:
            return full_brand_text
        
        # Define brand patterns - order matters (longer brands first)
        brand_patterns = [
            r'^Audemars Piguet',
            r'^Patek Philippe', 
            r'^Vacheron Constantin',
            r'^A\. Lange & Söhne',
            r'^Franck Muller',
            r'^Bell & Ross',
            r'^Tag Heuer',
            r'^Jaeger-LeCoultre',
            r'^Omega',
            r'^Rolex',
            r'^Tudor',
            r'^Cartier',
            r'^Hublot',
            r'^Breitling',
            r'^Panerai',
            r'^IWC',
            r'^Zenith',
            r'^Montblanc',
            r'^Longines',
            r'^Tissot',
            r'^Seiko',
            r'^Casio',
            r'^Citizen',
        ]
        
        for pattern in brand_patterns:
            match = re.search(pattern, full_brand_text, re.IGNORECASE)
            if match:
                brand_name = match.group(0)
                # Return in proper case for multi-word brands, uppercase for single words
                if ' ' in brand_name:
                    return brand_name  # Keep original case for multi-word brands
                else:
                    return brand_name.upper()  # Uppercase for single word brands
        
        # If no pattern matches, extract first word and uppercase it
        first_word = full_brand_text.split()[0] if full_brand_text.split() else full_brand_text
        return first_word.upper()

    def extract_product_basic_info(self, product_element) -> Dict:
        """
        Extract basic product information from listing page
        
        Args:
            product_element: BeautifulSoup element containing product data
            
        Returns:
            Dictionary with basic product information
        """
        product_data = {}
        
        try:
            # Extract product URL
            link_elem = product_element.find('a', class_='woocommerce-LoopProduct-link')
            if link_elem:
                product_data['product_url'] = link_elem.get('href', '')
            
            # Extract brand and model from h2 tag
            brand_model_elem = product_element.find('h2')
            if brand_model_elem:
                brand_model_text = brand_model_elem.get_text(strip=True)
                # Extract main brand name only
                product_data['brand'] = self.extract_main_brand_name(brand_model_text)
                # Store full text for description use
                product_data['_full_brand_model'] = brand_model_text
            
            # Extract reference number from h3 tag
            reference_elem = product_element.find('h3')
            if reference_elem:
                product_data['reference'] = reference_elem.get_text(strip=True)
            
            # Extract condition
            condition_elem = product_element.find('div', class_='pre-owned-cus')
            if condition_elem:
                product_data['condition'] = condition_elem.get_text(strip=True)
            
            # Extract price
            price_elem = product_element.find('span', class_='woocommerce-Price-amount')
            if price_elem:
                price_text = price_elem.get_text(strip=True)
                # Extract SGD price
                price_match = re.search(r'SGD\s*([\d,]+)', price_text)
                if price_match:
                    price_str = price_match.group(1).replace(',', '')
                    product_data['price_sgd'] = price_str
                else:
                    product_data['price_sgd'] = None
            
            # Initialize other fields with null values
            product_data['description'] = None
            product_data['year'] = None
            product_data['price_usd'] = None
            product_data['price_idr'] = None
            product_data['completeness'] = None
            
        except Exception as e:
            logger.error(f"Error extracting basic info: {e}")
        
        return product_data
    
    def extract_product_detailed_info(self, product_url: str) -> Dict:
        """
        Extract detailed product information from individual product page
        
        Args:
            product_url: URL of the individual product page
            
        Returns:
            Dictionary with detailed product information
        """
        detailed_info = {'description': None, 'year': None}
        
        if not product_url:
            return detailed_info
        
        soup = self.get_page(product_url)
        if not soup:
            return detailed_info
        
        try:
            # Extract description from meta tags first
            meta_desc = soup.find('meta', attrs={'name': 'description'})
            if meta_desc and meta_desc.get('content'):
                detailed_info['description'] = meta_desc.get('content').strip()
            
            # If no meta description, look for product description or summary
            if not detailed_info['description']:
                description_selectors = [
                    '.woocommerce-product-details__short-description',
                    '.entry-summary .woocommerce-product-details__short-description',
                    '.product-description',
                    '.summary .woocommerce-product-details__short-description p',
                    '.entry-summary p',
                    '.product-info p',
                    '.single-product-summary p'
                ]
                
                for selector in description_selectors:
                    desc_elem = soup.select_one(selector)
                    if desc_elem:
                        desc_text = desc_elem.get_text(strip=True)
                        if len(desc_text) > 20:  # Ensure it's meaningful content
                            detailed_info['description'] = desc_text
                            break
            
            # Extract year from structured JSON-LD data first
            structured_data = soup.find_all('script', type='application/ld+json')
            for script in structured_data:
                try:
                    if script.string:
                        data = json.loads(script.string)
                        if isinstance(data, dict):
                            # Look for release date or manufacturing date
                            if 'releaseDate' in data:
                                year_match = re.search(r'(\d{4})', str(data['releaseDate']))
                                if year_match:
                                    year_int = int(year_match.group(1))
                                    if 1950 <= year_int <= 2025:
                                        detailed_info['year'] = year_int
                                        break
                            
                            # Look for year in product description or name
                            if 'description' in data:
                                year_match = re.search(r'(\d{4})', str(data['description']))
                                if year_match:
                                    year_int = int(year_match.group(1))
                                    if 1950 <= year_int <= 2025:
                                        detailed_info['year'] = year_int
                                        break
                except (json.JSONDecodeError, ValueError):
                    continue
            
            # If no year from structured data, search in page content
            if not detailed_info['year']:
                page_text = soup.get_text()
                year_patterns = [
                    r'Year[:\s]*(\d{4})',
                    r'(\d{4})\s*model',
                    r'circa\s*(\d{4})',
                    r'manufactured\s*in\s*(\d{4})',
                    r'production\s*year[:\s]*(\d{4})'
                ]
                
                for pattern in year_patterns:
                    year_match = re.search(pattern, page_text, re.IGNORECASE)
                    if year_match:
                        year_int = int(year_match.group(1))
                        if 1950 <= year_int <= 2025:
                            detailed_info['year'] = year_int
                            break
            
        except Exception as e:
            logger.error(f"Error extracting detailed info from {product_url}: {e}")
        
        return detailed_info
    
    def scrape_page(self, page_num: int, include_details: bool = True) -> List[Dict]:
        """
        Scrape a single page of products
        
        Args:
            page_num: Page number to scrape
            include_details: Whether to fetch detailed info from individual pages
            
        Returns:
            List of product dictionaries
        """
        if page_num == 1:
            url = self.base_url
        else:
            url = f"{self.base_url}page/{page_num}/"
        
        soup = self.get_page(url)
        if not soup:
            return []
        
        products = []
        
        # Find all product elements
        product_elements = soup.find_all('li', class_='latest-single-product')
        
        logger.info(f"Found {len(product_elements)} products on page {page_num}")
        
        for i, product_elem in enumerate(product_elements, 1):
            try:
                # Extract basic info
                product_data = self.extract_product_basic_info(product_elem)
                
                if include_details and product_data.get('product_url'):
                    # Add delay between requests
                    time.sleep(self.delay)
                    
                    # Extract detailed info
                    detailed_info = self.extract_product_detailed_info(product_data['product_url'])
                    product_data.update(detailed_info)
                
                # Add metadata
                product_data.update({
                    'scraped_from': 'watchexchange.sg',
                    'scraped_at': datetime.now().isoformat(),
                    'product_type': 'watches'
                })
                
                products.append(product_data)
                
                logger.info(f"Scraped product {i}/{len(product_elements)}: {product_data.get('brand', 'Unknown')} {product_data.get('model', 'Unknown')}")
                
            except Exception as e:
                logger.error(f"Error processing product {i}: {e}")
                continue
        
        return products
    
    def get_total_pages(self) -> int:
        """
        Get the total number of pages available
        
        Returns:
            Total number of pages
        """
        soup = self.get_page(self.base_url)
        if not soup:
            return 1
        
        # Look for pagination info or load more button
        # From the HTML analysis, we know there are 27 pages total
        # But let's try to extract it dynamically
        try:
            # Look for pagination or load more button
            load_more_btn = soup.find('a', class_='lmp_button')
            if load_more_btn:
                href = load_more_btn.get('href', '')
                page_match = re.search(r'/page/(\d+)/', href)
                if page_match:
                    return int(page_match.group(1))
            
            # Look for result count to estimate pages
            result_count_elem = soup.find('h1', class_='woocommerce-result-count')
            if result_count_elem:
                count_text = result_count_elem.get_text()
                count_match = re.search(r'(\d+)\s*Pre-owned watches', count_text)
                if count_match:
                    total_products = int(count_match.group(1))
                    # Assuming 20 products per page
                    return (total_products + 19) // 20
        except:
            pass
        
        # Default fallback
        return 27
    
    def scrape_all_pages(self, include_details: bool = True) -> List[Dict]:
        """
        Scrape all available pages
        
        Args:
            include_details: Whether to fetch detailed info from individual pages
            
        Returns:
            List of all product dictionaries
        """
        total_pages = self.get_total_pages()
        logger.info(f"Starting to scrape {total_pages} pages")
        
        all_products = []
        
        for page_num in range(1, total_pages + 1):
            logger.info(f"Scraping page {page_num}/{total_pages}")
            products = self.scrape_page(page_num, include_details)
            all_products.extend(products)
            
            # Add delay between pages
            time.sleep(self.delay)
        
        return all_products
    
    def scrape_page_range(self, start_page: int, end_page: int, include_details: bool = True) -> List[Dict]:
        """
        Scrape a range of pages
        
        Args:
            start_page: Starting page number
            end_page: Ending page number (inclusive)
            include_details: Whether to fetch detailed info from individual pages
            
        Returns:
            List of product dictionaries
        """
        logger.info(f"Scraping pages {start_page} to {end_page}")
        
        all_products = []
        
        for page_num in range(start_page, end_page + 1):
            logger.info(f"Scraping page {page_num}")
            products = self.scrape_page(page_num, include_details)
            all_products.extend(products)
            
            # Add delay between pages
            time.sleep(self.delay)
        
        return all_products

def main():
    parser = argparse.ArgumentParser(description='Scrape watch data from WatchExchange.sg')
    
    # Scraping mode options
    mode_group = parser.add_mutually_exclusive_group(required=True)
    mode_group.add_argument('--all', action='store_true', help='Scrape all pages')
    mode_group.add_argument('--pages', nargs=2, type=int, metavar=('START', 'END'), 
                           help='Scrape pages from START to END (inclusive)')
    mode_group.add_argument('--page', type=int, help='Scrape a single page')
    
    # Output options
    parser.add_argument('--output', '-o', required=True, help='Output JSON filename')
    parser.add_argument('--delay', type=float, default=1.0, help='Delay between requests in seconds (default: 1.0)')
    parser.add_argument('--no-details', action='store_true', help='Skip detailed info extraction (faster)')
    
    args = parser.parse_args()
    
    # Initialize scraper
    scraper = WatchScraper(delay=args.delay)
    
    # Determine what to scrape
    include_details = not args.no_details
    
    if args.all:
        logger.info("Scraping all pages...")
        products = scraper.scrape_all_pages(include_details)
    elif args.pages:
        start_page, end_page = args.pages
        logger.info(f"Scraping pages {start_page} to {end_page}...")
        products = scraper.scrape_page_range(start_page, end_page, include_details)
    elif args.page:
        logger.info(f"Scraping page {args.page}...")
        products = scraper.scrape_page(args.page, include_details)
    
    # Save to JSON
    logger.info(f"Saving {len(products)} products to {args.output}")
    
    with open(args.output, 'w', encoding='utf-8') as f:
        json.dump(products, f, indent=2, ensure_ascii=False)
    
    logger.info(f"Successfully saved {len(products)} products to {args.output}")
    
    # Print summary
    if products:
        sample_product = products[0]
        logger.info("Sample product structure:")
        for key, value in sample_product.items():
            logger.info(f"  {key}: {value}")

if __name__ == "__main__":
    main()