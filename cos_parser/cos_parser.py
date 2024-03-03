#!/usr/bin/env python3

import requests
from bs4 import BeautifulSoup
from pymongo import MongoClient


from pprint import pprint
import traceback
import os
import re
import sys
import json
import toml
import shutil

from utils import translate, download_and_save_image, loadPhoto, make_request

# ! CONFIG 
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG = toml.load(f'CONFIG.toml')
COS_CONFIG = CONFIG['ParserManager']['cos_parser_path']

class CosParser:
    def __init__(self, categoryTableName, mode, headers, cookies, collection):
        self.brand = 'cos'
        self.host = 'https://www.cos.com'
        
        self.categoryTableName = categoryTableName
        self.mode = mode
        self.headers = headers
        self.cookies = cookies
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
        inserted_count = 0
        urls = self.getAllProducts()
        for url in urls:
            data = {}
            
            print(f'{urls.index(url) + 1} of {len(urls)}. Parse URL:', url)
            
            response = requests.get(url, headers=self.headers, cookies=self.cookies)
            html = response.text
            
            soup = BeautifulSoup(html, 'lxml')
            
            productData = self.getProductDataFromJS(html)
            
            name = translate(productData['name'])
            originalPrice = float(soup.find('span', {'class': 'productPrice'}).text.strip()[2:].replace(',', '.'))

            price = self.getPrice(originalPrice)
            
            fullArticle = re.search(r'[0-9]{10}', url).group(0)
            productArticle = fullArticle[:-3]
            uniq_article = self.brand + '_' + productArticle
            
            description = str(soup.find('div', {'id': 'description'}))
            pattern = re.compile(r'<p>(.*?)</p>', re.DOTALL)
            description = ' '.join([i.strip() for i in pattern.findall(description)])
            
            material = []
            for word in description.split('% '):
                for i in self.MATERIALS.keys():
                    if word.lower().startswith(i):
                        material.append(self.MATERIALS[i])
                        break
            description = translate(description)
            material = ';'.join(list(set(material)))
            
            colors = []
            for key in productData.keys():
                colorData = {}
                if re.match(r'[0-9]{10}', key):
                    originalColor = productData[key]['name']
                    try:
                        color = self.COLORS[originalColor.upper()]['name']
                    except KeyError:
                        color = 'разноцветный'
                    try:
                        hexCode = self.COLORS[originalColor.upper()]['hexCode']
                    except KeyError:
                        hexCode = '#FFFFFF'
                    code = key[-3:]
                    
                    images = productData[key]['vAssets']
                    
                    imagePathes = []
                    for image in images:
                        img_url = 'http:' + image['thumbnail']
                        
                        filepath = download_and_save_image(img_url, f'photo/{self.brand}_{productArticle}_{color.replace("/", "_")}_{images.index(image)}')
                        if filepath:
                            imagePathes.append(filepath)
                    
                    loadPhoto(self.brand, productArticle, color, imagePathes)
                    
                    sizes = []
                    
                    for size in productData[key]['variants']:
                        sizes.append({'name': size['sizeName'], 'code': size["sizeCode"], 'availability': ''})
                    
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
    
    def getAllProducts(self):
        response = requests.get(self.CATEGORY_URL, headers=self.headers, cookies=self.cookies)
        html = response.text
        soup = BeautifulSoup(html, 'lxml')
        
        urls = [i.find('a').get('href') for i in soup.find_all('div', class_="image-if-hover")]
        urls = self.remove_duplicate_links(urls)
        
        return urls

    def remove_duplicate_links(self, links):
        seen_prefixes = set()
        unique_links = []

        for link in links:
            prefix = re.match(r'.*\.([0-9]{10})\.html', link).group(1)[:7]
            if prefix not in seen_prefixes:
                unique_links.append(link)
                seen_prefixes.add(prefix)

        return unique_links
    
    def modeUpdate(self):
        filter_criteria = {"brand": self.brand}
        projection = {'_id': False, 'article': True, 'colors': True, 'deliveryPrice': True}


        result = self.collection.find(filter_criteria, projection)
        updated_count = 0
        for document in result:     
            article = document['article']
            print('Parse article:', article)
            colors = document['colors']
            self.DELIVERY_PRICE = document['deliveryPrice']
            
            url = f'https://www.cos.com/webservices_cos/service/product/cos-europe/availability/{article}.json'        
            jsonData = make_request(url, headers=self.headers).text
            dct = json.loads(jsonData)
            availableProducts = dct['availability'] + dct['fewPieceLeft']
            if availableProducts == []:
                for i in range(len(colors)):
                    for j in range(len(colors[i]['sizes'])):
                        colors[i]['sizes'][j]['availability'] = 'out_of_stock'
            else:
                url = f'https://www.cos.com/en_eur/women/womenswear/tops/product.oversized-t-shirt-black.{availableProducts[0][:-3]}.html'
                html = make_request(url, headers=self.headers).text
                soup = BeautifulSoup(html, 'lxml')
                originalPrice = float(soup.find('span', {'class': 'productPrice'}).text.strip()[2:].replace(',', '.'))
                price = self.getPrice(originalPrice)
                
                for i in range(len(colors)):
                    for j in range(len(colors[i]['sizes'])):
                        fullArticle = str(article) + str(colors[i]['code']) + str(colors[i]['sizes'][j]['code'])
                        
                        if fullArticle in availableProducts:
                            colors[i]['sizes'][j]['availability'] = 'in_stock'
                        else:
                            colors[i]['sizes'][j]['availability'] = 'out_of_stock'
                    
            filter_criteria = {"article": article} 
            
            new_record = {"originalPrice": originalPrice, "price": price, "colors": colors}
                                    
            try:
                update_result = self.collection.update_one(filter_criteria, {'$set': new_record})
                if update_result.modified_count == 1:
                    updated_count += 1
            except Exception as e:
                print(e)


        print("Updated:", updated_count)
    
    def gPriceDict(self, key):
        return float(self.PRICE_TABLE[key])

    def getPrice(self, eur_price):
        cost_price = (float(eur_price) * self.gPriceDict(
            'КУРС_EUR_RUB')) + (self.DELIVERY_PRICE * self.gPriceDict(
            'КУРС_БЕЛ.РУБ_РУБ') * self.gPriceDict(
            'КУРС_EUR_БЕЛ.РУБ'))
        final_price = (cost_price) / (
                1 - self.gPriceDict('НАЦЕНКА') - self.gPriceDict(
            'ПРОЦЕНТЫ_НАЛОГ') - self.gPriceDict('ПРОЦЕНТЫ_ЭКВАЙРИНГ'))

        final_price = (final_price // 100 + 1) * 100 - 10
        return final_price

    def getProductDataFromJS(self, html):
        regexp = re.compile(r'var\s+productArticleDetails\s*=\s*(\{.*?\});', re.DOTALL)


        output_str = re.search(regexp, html).group(1).replace("'", '"')
            
        output_str = re.sub(r'"sizeName" : "(.*)",', r'"sizeName" : "\1"', output_str)
        
        output_str = re.sub(r'"materials": \[([^\[\]]*)\],', '"materials": [""],', output_str)
        output_str = re.sub(r'"url":[^\n]*', '"url": "",', output_str)
        output_str = re.sub(r'"url": "",\s*}', '"url": ""}', output_str)
        output_str = re.sub(r'"image":\s*isDesktop\s*\?\s*"(.*)"\s*:\s*"(.*)"', r'"image": "\1"', output_str)
        output_str = re.sub(r'getPro"fullscreen":[^\n]*', '"fullscreen": "",', output_str)
        output_str = re.sub(r'"recommendedDelivery":[^\n]*', '"recommendedDelivery": ""', output_str)
        pattern = re.compile(r'"compositions": \[.*?\],', re.DOTALL)
        output_str = re.sub(pattern, '"compositions": [],', output_str)
        
        output_str = re.sub(r'"zoom":[^\n]*', '"zoom": ""', output_str)
            
        result = json.loads(output_str)
        
        return result
    
    def loadParserSettings(self):
        with open(f'{COS_CONFIG}/categories.json', 'r', encoding='utf-8') as f:
            categories = json.load(f)
        with open(f'{COS_CONFIG}/colors.json', 'r', encoding='utf-8') as f:
            self.COLORS = json.load(f)
        with open(f'{COS_CONFIG}/materials.json', 'r', encoding='utf-8') as f:
            self.MATERIALS = json.load(f)
        with open(f'{COS_CONFIG}/priceTable.json', 'r', encoding='utf-8') as f:
            self.PRICE_TABLE = json.load(f)
        
        self.CATEGORY_URL = categories[self.categoryTableName]['url']
        self.PARSE_TYPE = categories[self.categoryTableName]['type_pars']
        self.DELIVERY_PRICE = float(categories[self.categoryTableName]["ЦЕНА_ДОСТАВКИ_В_КАТЕГОРИИ"])
        
        self.CATEGORY = categories[self.categoryTableName]['category']
        self.SUBCATEGORY = categories[self.categoryTableName]['subcategory']
        self.GENDER = categories[self.categoryTableName]['gender']
    
    def loadUpdateSettings(self):
        with open(f'{COS_CONFIG}/priceTable.json', 'r', encoding='utf-8') as f:
            self.PRICE_TABLE = json.load(f)
        

def main(mode, category=None):
    """
    :mode - parser or update
    :category - name of category
    """
    print('[COS_PARSER]\nmode',mode,'\ncategory',category)

    if mode==1:
        mode = 'update'
    else:
        mode = 'parser'
    
    if mode=='parser':
        COLLECTION_NAME = 'tmp_Products'
    else:
        COLLECTION_NAME = 'tmp_Products'

    
    dbClient = MongoClient(host=CONFIG['Server']['host'],port=CONFIG['Server']['port'],username='admin',password=CONFIG['Server']['db_password'])
    db = dbClient['DB']
    collection = db[COLLECTION_NAME]
    
    headers = {
        "Host": "www.cos.com",
        "Cache-Control": "max-age=0",
        "Sec-Ch-Ua": '"Chromium";v="119", "Not?A_Brand";v="24"',
        "Sec-Ch-Ua-Mobile": "?0",
        "Sec-Ch-Ua-Platform": '"Linux"',
        "Upgrade-Insecure-Requests": "1",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.6045.199 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
        "Sec-Fetch-Site": "same-origin",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-User": "?1",
        "Sec-Fetch-Dest": "document",
        "Accept-Encoding": "gzip, deflate, br",
        "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
        "Priority": "u=0, i"
    }
    
    cookies = dict(make_request('https://www.cos.com', headers=headers).cookies)
    cookies.update({'HMCORP_locale': 'pl_PL', 'HMCORP_currency': 'EUR', 'AKA_A2': 'A', 'countryId': 'PL'})
        
    if 'photo' not in os.listdir():
        os.mkdir('photo')
    
    parser = CosParser(category, mode, headers, cookies, collection)
    parser.parse()
    
    dbClient.close()
    
    shutil.rmtree('photo')

    return True


if __name__ == '__main__':
    # load_dotenv()
    try:
        mode = sys.argv[1]
        category = sys.argv[2]
    except IndexError:
        print(f"Usage: {sys.argv[0]} <mode> <category>")
        sys.exit()
    
    main(int(mode), category)
