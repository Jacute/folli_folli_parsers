import requests
from deep_translator import GoogleTranslator
import traceback
import urllib3
from urllib3.exceptions import InsecureRequestWarning
import os
from requests.exceptions import RequestException
from time import sleep

from PIL import Image
from io import BytesIO
import imghdr
import toml


CONFIG = toml.load(f'CONFIG.toml')

def loadPhoto(brand, article, color, imagePathes):
    upload_url = 'https://83.147.245.51:5000/upload_imgs/{}_{}_{}'
    upload_url = upload_url.format(brand, article, color.replace('/','_'))

    files = {}
    for imagePath in imagePathes:
        filename = os.path.basename(imagePath)
        
        files[filename] = open(imagePath, 'rb')
    
    try:
        response = make_request(upload_url, 'post', files=files).text
        if response.lower() == 'success':
            return True
        raise Exception(f'Error! Response: {response}')
    except Exception as e:
        print(e)
        return False
    


def translate(text, retries=2, delay=1):
    for _ in range(retries + 1): # retries 3 times
        try:
            translated = GoogleTranslator(source='auto', target='ru').translate(text)
            return translated
        except Exception as e:
            print(f"Error: {e}")
            if _ < retries:
                print(f"Retrying in {delay} seconds...")
                sleep(delay)
    return None


def download_and_save_image(url, filepath):
    try:
        response = make_request(url)
    
        if response.status_code == 200:
            image_format = 'jpg'

            if image_format:
                image = Image.open(BytesIO(response.content))

                save_path = filepath + '.' + image_format
                
                image.save(save_path)
                return save_path
    except:
        traceback.print_exc()
        print("Error downloading image. URL:", url)
    return None


def make_request(url, method='get', headers=None, cookies=None, files=None, retries=2, delay=1):
    urllib3.disable_warnings(InsecureRequestWarning) # disable https invalid cert verification warnings
    
    for _ in range(retries + 1):
        try:
            if method == 'post':
                response = requests.post(url, headers=headers, cookies=cookies, files=files, verify=False)
            else:
                response = requests.get(url, headers=headers, cookies=cookies)
            response.raise_for_status()  # Бросает исключение для 4xx и 5xx кодов ответа
            return response
        except RequestException as e:
            print(f"Error: {e}")
            if _ < retries:
                print(f"Retrying in {delay} seconds...")
                sleep(delay)
    return None  # Если все попытки завершились неудачей


if __name__ == "__main__":
    upload_url = 'https://83.147.245.51:5000/upload_imgs/{}_{}_{}'
    
    headers = {
            'User-Agent': 'Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:121.0) Gecko/20100101 Firefox/121.0',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
            'Accept-Language': 'ru-RU,ru;q=0.8,en-US;q=0.5,en;q=0.3',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'same-origin',
            'Sec-Fetch-User': '?1',
            'TE': 'trailers',
        }
    res = loadPhoto('cos', '1218159', '272628', ['photo/cos_1218159_белый_0.jpg'])
    print(res)
