import os
import json
from tqdm import tqdm
import layoutparser as lp
import tesserocr
from PIL import Image
import cv2
import multiprocessing as mp
import concurrent.futures
from concurrent.futures import ProcessPoolExecutor
import pdfminer
from pdfminer.high_level import extract_pages
import matplotlib.pyplot as plt
from pypdf import PdfReader
import re
from multiprocessing import Manager
import numpy as np

from src.process.segmentation import lp_detect, MODELS
from src.datautils.dataloader import read_img

BS = 10

def load_vocab():
    with open('./src/es.txt') as file:
        lines = file.readlines()
    return [line.strip().lower() for line in lines]
VOCAB = load_vocab()

def preprocess(image):
    image = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    image = cv2.equalizeHist(image)
    image = cv2.GaussianBlur(image, (5, 5), 1)
    return image

def ocr_img(img):
    return tesserocr.image_to_text(Image.fromarray(img), lang = 'spa')

def post_process(text):
    spplited = re.sub(r'[^\w\s]|_', ' ', text).split()
    newtext = []
    skip = False
    for n, word in enumerate(spplited[:-1]):
        if skip:
            skip = False
            continue

        comb = word + spplited[n+1]
        if  (comb.lower() in VOCAB) and (len(word) >= 2) and len(comb) > 4:
            
            newtext.append(comb)
            skip = True
        else: 
            newtext.append(word)
    return " ".join(newtext)

def extract_text_with_position(page_layout, page, max_x, max_y, x, y, x2, y2):
    text = ""

    for element in list(extract_pages(page_layout))[page]:
        if isinstance(element, pdfminer.layout.LTTextBoxHorizontal):
            for text_line in element:
                for character in text_line:
                    if isinstance(character, pdfminer.layout.LTChar):
                        x_pixels, y_pixels, _, _ = character.bbox
                        
                        arr_pixel_x = (x_pixels /  max_x) 
                        arr_pixel_y = 1- (y_pixels / max_y)

                        if x <= (arr_pixel_x) <= x2 and y <= (arr_pixel_y) <= y2:
                            char = character.get_text()
                            text += char
    return post_process(text)

def save_file(fname):
    files = read_img(fname)
    pre, _ = os.path.splitext(files)
    np.savez_compressed(pre + '.npz', files)
    return True

def just_save_numpy(folder, mp_general = 6):
    file_extensions = ['.pdf',]
    print(f"Function triggered with origin {folder}")
    files = []

    for root, _, files in os.walk(folder):
        for file in tqdm(files, desc=f"Processing {folder}..."):
            if not (os.path.splitext(file)[1].lower() in file_extensions): continue

            fname = os.path.join(root, file)
            files.append(fname)

    with ProcessPoolExecutor(max_workers=mp_general) as executor:
        tasks = {executor.submit(save_file, img): file for img in files}
        for future in tqdm(concurrent.futures.as_completed(tasks)):
            _ = future.result()
            


def paralel_extract_wrapper(args):
    return extract_text_with_position(*args)

def process_folder(folder, out_base, LPMODEL, mp_ocr = 0, ocr = True, margin = 10):
    file_extensions = ['.pdf',]
    print(f"Function triggered with origin {folder} and destination {out_base}")

    out = out_base
    os.makedirs(out, exist_ok=True)
    manager = Manager()

    for root, _, files in os.walk(folder):
        for file in tqdm(files, desc=f"Processing {folder}..."):
            outname = os.path.join(out, file.lower().replace('.pdf', '.json'))

            if not os.path.splitext(file)[1].lower() in file_extensions: continue
            if os.path.exists(outname): continue

            fname = os.path.join(root, file)
            images = read_img(fname)
            manager = mp.Manager()
            json_gt = {
                    "file": file, 
                    "path": fname,
                    "pages": {}
                    }
            pdfhandler = PdfReader(fname).pages

            for num, image in enumerate(images):

                json_gt["pages"][num] = []
                detection = lp_detect(image, LPMODEL)

                returned = manager.list([None] * len(detection)) if mp_ocr else [None] * len(detection)
                image = preprocess(image)
                _, _, max_x, max_y = pdfhandler[num].mediabox
                
                if mp_ocr:
                    crops = []

                for mp_num, item in enumerate(detection):
                    

                    json_gt["pages"][num].append(
                        {"type": item.type, "bbox": [int(x) for x in item.coordinates], 'conf': item.score}
                    )
                    x,y,w,h = [int(x) for x in item.coordinates]
                    crop = image[y:max(h-1,0), x:max(w-1, 0)]
                    x, y = x-margin, y - margin  
                    w,h = w+margin, h+margin
                    if not mp_ocr:
                        # text =   tesserocr.image_to_text(crop, lang = 'spa')  #OCR.readtext(crop)
                        text = extract_text_with_position(fname, num, max_x, max_y, x = x / image.shape[1], y= y/image.shape[0], x2=w/image.shape[1], y2=h/image.shape[0])
                        
                        returned[num] = text
                    else: crops.append([fname, num, max_x, max_y, x / image.shape[1], y/image.shape[0], w/image.shape[1], h/image.shape[0]])
                
                if mp_ocr:
                    with ProcessPoolExecutor(max_workers=mp_ocr) as executor:
                        tasks = {executor.submit(paralel_extract_wrapper, img): n for n, img in enumerate(crops)}
                        for future in concurrent.futures.as_completed(tasks):
                            crop_number = tasks[future]
                            returned[crop_number] = future.result()

                for mp_num, element in enumerate(returned):
                    if element is not None: json_gt["pages"][num][mp_num]['ocr'] = element
            
            json.dump(dict(json_gt), open(outname, 'w')) # TODO: Ensure it arrives here on join            
    del LPMODEL


def rescale(image, x, y, w, h, model):
    longest = max(image.shape)
    if longest < model.cfg.INPUT.MAX_SIZE_TEST: return x, y, w, h
    scale = longest / model.cfg.INPUT.MAX_SIZE_TEST 
    return int(scale * x), int(scale * y), int(scale * w), int(scale * h)

    