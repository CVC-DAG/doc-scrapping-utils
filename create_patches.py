
import multiprocessing as mp
import json 
import argparse
import os
import layoutparser as lp
import concurrent.futures
from concurrent.futures import ProcessPoolExecutor

from src.datautils.create_json_scheme import process_folder
from src.process.segmentation import MODELS


if __name__ == '__main__':
    mp.set_start_method('spawn')


    parser = argparse.ArgumentParser(
                        prog='Lorem Ipsum',
                        description='Super Trouper',
                        epilog='Uwu')

    parser.add_argument('-s', '--subset', default="gazeta-modern")
    parser.add_argument('-w', '--where_data', default="/data1tbsdd/BOE/")
    parser.add_argument('-o', '--outdir', default="data/BOE/{}/jsons")
    parser.add_argument('-t', '--threads', default=2, type=int)
    parser.add_argument('-dd', '--device_detection', default='cuda:1', type=str)
    parser.add_argument('-do', '--mp_ocr', default=0, type=int)
    parser.add_argument('-ocr', '--ocr', default=False, type=bool)
    parser.add_argument('-docr', '--device_ocr', default='cuda:0', type=str)


    args = parser.parse_args()
    LPMODEL = lp.models.Detectron2LayoutModel(
            config_path =MODELS["prima"]['model'], # In model catalog
            label_map   = MODELS["prima"]["labels"], # In model`label_map`
            extra_config=["MODEL.ROI_HEADS.SCORE_THRESH_TEST", 0.8] # Optional
        )
    LPMODEL.device = args.device_detection 

    subset = [x for x in json.load(open('jsons/subsets.json', 'r'))["subsets"] if x["name"] == args.subset][0]
    print(f"Using {subset} subset")

    # folder, out_base, LPMODEL, mp_ocr = 0, ocr = True, ocr_device = 'cuda', margin = 10, file_extensions = ['.pdf',]
    folders = [(os.path.join(args.where_data, f), args.outdir.format(f), LPMODEL, args.mp_ocr, args.ocr, args.device_ocr) for f in subset["subfolders"]]

    if args.threads:
        with mp.Pool(args.threads) as p: p.starmap(process_folder, folders)

    else:
        for folder in folders:
            process_folder(*folder)