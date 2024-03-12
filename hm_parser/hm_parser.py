#!/usr/bin/env python3

import requests
from bs4 import BeautifulSoup
from pymongo import MongoClient
import toml

import traceback
import os
import re
import sys
import json
import shutil

from utils import translate, download_and_save_image, loadPhoto, make_request



# ! CONFIG 
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG = toml.load(f'CONFIG.toml')
HM_CONFIG = CONFIG['ParserManager']['hm_parser_path']


class HMParser:
    def __init__(self, categoryTableName, mode, headers, collection):
        self.brand = 'h&m'
        self.host = 'https://www2.hm.com'
        
        self.categoryTableName = categoryTableName
        self.mode = mode
        self.headers = headers
        self.collection = collection
    
    def parse(self):
        if self.mode == 'parser':
            self.loadParserSettings()
            self.modeParser() 
        elif self.mode == 'update':
            self.loadUpdateSettings()
            self.modeUpdate()   
        else:
            print('Unknown mode')
            sys.exit()
    
    def modeParser(self):    
        response = make_request(self.CATEGORY_URL, headers=self.headers)
        html = response.text
        soup = BeautifulSoup(html, 'lxml')
        
        products = soup.find_all('div', class_='c02f13')
        products = [i.find('a') for i in products]
        
        inserted_count = 0
        urls = []
        for product in products:
            url = product['href']
            urls.append(url)
        
        urls = self.remove_duplicate_links(urls)
        
        for url in urls:
            data = {}
            
            print(f'{urls.index(url) + 1} of {len(urls)}. Parse URL:', url)
            
            response = make_request(url, headers=self.headers)
            html = response.text
            
            """with open('last_page.html', 'w') as f:
                f.write(html)"""
            
            soup = BeautifulSoup(html, 'lxml')
                

            name = translate(soup.h1.text)
            productArticle = re.search(r'\.[0-9]+\.', url).group()[1:-4] # H&M_0975846001_XXS
            uniq_article = f'{self.brand}_{productArticle}'
            
            
            originalPrice = soup.find('span', class_='price-value').text
            if 'Cena dla Klubowiczów' in originalPrice:
                originalPrice = originalPrice[:originalPrice.find('Cena dla Klubowiczów')]
            originalPrice = float(re.findall(r'[0-9 ]+,\d+', originalPrice)[0].replace(',', '.').replace(' ', '').strip())
            price = self.getPrice(originalPrice)
                    
            description = translate(soup.find('div', id='section-descriptionAccordion').find('p').text)
            material = translate(soup.find('div', id='section-materialsAndSuppliersAccordion').find('p').text)

            productData = self.getProductDataFromJS(html)

            colors = []
            for key in productData.keys():
                colorData = {}
                if re.match(r'[0-9]{10}', key):
                    originalColor = productData[key]['name']
                    try:
                        color = self.COLORS[originalColor]
                    except KeyError:
                        color = 'разноцветный'
                    hexCode = productData[key]['rgb']
                    code = key[-3:]
                    
                    images = productData[key]['images']
                    
                    imagePathes = []
                    for image in images:
                        img_url = 'http:' + image['image']
                        
                        filepath = download_and_save_image(img_url, f'photo/{self.brand}_{productArticle}_{color.replace("/", "_")}_{images.index(image)}')
                        if filepath:
                            imagePathes.append(filepath)
                    loadPhoto(self.brand, productArticle, color, imagePathes)
                    
                    sizes = []
                    
                    for size in productData[key]['sizes']:
                        sizes.append({'name': size['name'], 'code': size["size"], 'availability': ''})
                    
                    colorData['name'] = color
                    colorData['originalName'] = originalColor
                    colorData['code'] = code
                    colorData['hexCode'] = hexCode
                    colorData['sizes'] = sizes
                    colors.append(colorData)
            

            
            data['name'] = name
            data['article'] = productArticle
            data['uniq_article'] = uniq_article
            data['brand'] = self.brand
            data['type'] = self.PARSE_TYPE
            data['category'] = self.CATEGORY
            data['gender'] = self.GENDER
            data['subcategory'] = self.SUBCATEGORY
            data['description'] = description
            data['price'] = price
            data['originalPrice'] = originalPrice
            data['deliveryPrice'] = self.DELIVERY_PRICE
            
            data['colors'] = colors     
            data['material'] = material
            data['care'] = "Машинная стирка при температуре до 30ºC с коротким циклом отжима.Отбеливание запрещено.Гладить при температуре до 110ºC .Химчистка с тетрахлорэтиленом.Не использовать машинную сушку"
            
            try:
                result = self.collection.insert_one(data)
                inserted_count += 1
                
                print("Inserted document ID:", result.inserted_id)
            except Exception as e:
                print(e)
        print("Inserted:", inserted_count)
    
    def modeUpdate(self):
        filter_criteria = {"brand": self.brand}
        projection = {'_id': False, 'article': True, 'colors': True, 'deliveryPrice': True}


        result = self.collection.find(filter_criteria, projection)
        updated_count = 0
        for document in result:            
            article = document['article']
            colors = document['colors']
            self.DELIVERY_PRICE = document['deliveryPrice']
            
            try:
                url = f'https://www2.hm.com/hmwebservices/service/product/pl/availability/{article}.json'   
                try:    
                    jsonData = make_request(url, headers=self.headers).text
                except:
                    print("Skip URL:", url)
                    continue
                dct = json.loads(jsonData)
                availableProducts = dct['availability'] + dct['fewPieceLeft']
                if availableProducts == []:
                    for i in range(len(colors)):
                        for j in range(len(colors[i]['sizes'])):
                            colors[i]['sizes'][j]['availability'] = 'out_of_stock'
                else:
                    url = f'https://www2.hm.com/pl_pl/productpage.{availableProducts[0][:-3]}.html'
                    print('Parse URL:', url)
                    try:
                        html = make_request(url, headers=self.headers).text
                    except:
                        print("Skip URL:", url)
                        continue
                    soup = BeautifulSoup(html, 'lxml')
                    originalPrice = float(soup.find('span', class_='price-value').text.strip().replace(' PLN', '').replace(',', '.'))
                    price = self.getPrice(originalPrice)
                    
                    for i in range(len(colors)):
                        for j in range(len(colors[i]['sizes'])):
                            fullArticle = str(article) + str(colors[i]['code']) + str(colors[i]['sizes'][j]['code'])
                            
                            if fullArticle in availableProducts:
                                colors[i]['sizes'][j]['availability'] = 'in_stock'
                            else:
                                colors[i]['sizes'][j]['availability'] = 'out_of_stock'
            except:
                print("Skip URL:", url)
                continue
            filter_criteria = {"article": article} 
            
            new_record = {"originalPrice": originalPrice, "price": price, "colors": colors}
                                    
            try:
                update_result = self.collection.update_one(filter_criteria, {'$set': new_record})
                if update_result.modified_count == 1:
                    updated_count += 1
            except Exception as e:
                print(e)


        print("Updated:", updated_count)
    
    def remove_duplicate_links(self, links):
        seen_prefixes = set()
        unique_links = []

        for link in links:
            prefix = re.match(r'.*\.([0-9]{10})\.html', link).group(1)[:7]
            if prefix not in seen_prefixes:
                unique_links.append(link)
                seen_prefixes.add(prefix)

        return unique_links
    
    def getProductDataFromJS(self, html):
        regexp = re.compile(r'var\s+productArticleDetails\s*=\s*(\{.*?\});', re.DOTALL)


        output_str = re.search(regexp, html).group(1).replace("'", '"')

        output_str = re.sub(r'"materials": \[([^\[\]]*)\],', '"materials": [""],', output_str)
        output_str = re.sub(r'"url":[^\n]*', '"url": "",', output_str)
        output_str = re.sub(r'"thumbnail":[^\n]*', '"thumbnail": "",', output_str)
        output_str = re.sub(r'"image":\s*isDesktop\s*\?\s*"(.*)"\s*:\s*"(.*)"', r'"image": "\1"', output_str)
        output_str = re.sub(r'"fullscreen":[^\n]*', '"fullscreen": "",', output_str)
        output_str = re.sub(r'"recommendedDelivery":[^\n]*', '"recommendedDelivery": ""', output_str)
        output_str = re.sub(r'"brandPagePath":[^\n]*', '"brandPagePath": ""', output_str)
        output_str = re.sub(r'"zoom":[^\n]*', '"zoom": ""', output_str)
        output_str = re.sub(r'"deliveryBulkyText":[^\n]*', ',"deliveryBulkyText": ""', output_str)
            
        with open('output.json', 'w') as f:
            f.write(output_str)
            
        result = json.loads(output_str)
        
        return result
        
    
    def gPriceDict(self, key):
        return float(self.PRICE_TABLE[key])

    def getPrice(self, pln_price):
        cost_price = ((float(pln_price) / self.gPriceDict("КУРС_USD_ЗЛОТЫ")) * self.gPriceDict("КОЭФ_КОНВЕРТАЦИИ") * self.gPriceDict(
            'КУРС_USD_RUB')) + (self.DELIVERY_PRICE * self.gPriceDict('КУРС_БЕЛ.РУБ_РУБ') * self.gPriceDict(
            'КУРС_EUR_БЕЛ.РУБ'))
        final_price = (cost_price ) / (
                    1 - self.gPriceDict('НАЦЕНКА')  - self.gPriceDict('ПРОЦЕНТЫ_НАЛОГ') - self.gPriceDict('ПРОЦЕНТЫ_ЭКВАЙРИНГ'))

        final_price = (final_price // 100 + 1) * 100 - 1
        return final_price
    
    def loadParserSettings(self):
        with open(f'{HM_CONFIG}/categories.json', 'r', encoding='utf-8') as f:
            categories = json.load(f)
        with open(f'{HM_CONFIG}/colors.json', 'r', encoding='utf-8') as f:
            self.COLORS = json.load(f)
        with open(f'{HM_CONFIG}/priceTable.json', 'r', encoding='utf-8') as f:
            self.PRICE_TABLE = json.load(f)
        
        self.CATEGORY_URL = categories[self.categoryTableName]['url']
        self.PARSE_TYPE = categories[self.categoryTableName]['type_pars']
        self.DELIVERY_PRICE = float(categories[self.categoryTableName]["ЦЕНА_ДОСТАВКИ_В_КАТЕГОРИИ"])
        
        self.CATEGORY = categories[self.categoryTableName]['category']
        self.SUBCATEGORY = categories[self.categoryTableName]['subcategory']
        self.GENDER = categories[self.categoryTableName]['gender']
    
    def loadUpdateSettings(self):
        with open(f'{HM_CONFIG}/priceTable.json', 'r', encoding='utf-8') as f:
            self.PRICE_TABLE = json.load(f)
    

def main(mode, category=None):
    """
    :mode - parser or update
    :category - name of category
    """
    print('[HM_PARSER]\nmode',mode,'\ncategory',category)
    DB_NAME = 'DB'

    if mode==1:
        mode = 'update'
    else:
        mode = 'parser'


    if mode=='parser':
        COLLECTION_NAME = 'tmp_Products'
    else:
        COLLECTION_NAME = 'Products'

    
    dbClient = MongoClient(host=CONFIG['Server']['host'],port=CONFIG['Server']['port'],username='admin',password=CONFIG['Server']['db_password'])

    db = dbClient[DB_NAME]
    collection = db[COLLECTION_NAME]
    
    headers = {
            'User-Agent': '123'
        }
    
    if 'photo' not in os.listdir():
        os.mkdir('photo')
    
    parser = HMParser(category, mode, headers, collection)
    parser.parse()
    
    dbClient.close()

    shutil.rmtree('photo')

    
    return True


if __name__ == '__main__':

    try:
        mode = sys.argv[1]
        category = sys.argv[2]
    except IndexError:
        print(f"Usage: {sys.argv[0]} <mode> <category>")
        sys.exit()
    
    main(int(mode), category)
