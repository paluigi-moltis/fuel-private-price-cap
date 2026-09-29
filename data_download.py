from pymongo import MongoClient
from dotenv import load_dotenv
import os

load_dotenv()

client = MongoClient(os.getenv('MONGO_URI'))

prices = client['fuels']['prices'].aggregate([
    {
        '$match': {
            'date': {
                '$gte': '2026-07-01'
            }, 
            'isSelf': 1, 
            'descCarburante': {
                '$in': [
                    'Benzina', 'Gasolio'
                ]
            }
        }
    }, {
        '$project': {
            '_id': 0
        }
    }
])

stations = client['fuels']['stations'].aggregate([
    {
        '$project': {
            '_id': 0, 
            'idImpianto': 1, 
            'Gestore': 1, 
            'Bandiera': 1, 
            'Tipo Impianto': 1, 
            'Provincia': 1, 
            'Latitude': 1, 
            'Longitude': 1, 
            'date': 1
        }
    }
])

tax = client['fuels']['tax'].aggregate([
    {
        '$project': {
            '_id': 0, 
            'application_date': 1, 
            'benzina_tax': 1, 
            'gasolio_tax': 1
        }
    }, {
        '$match': {
            'application_date': {
                '$gte': '2026-05-01'
            }
        }
    }, {
        '$sort': {
            'application_date': 1
        }
    }
])
