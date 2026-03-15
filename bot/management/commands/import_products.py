import csv
import os
from django.core.management.base import BaseCommand
from bot.models import Product

class Command(BaseCommand):
    help = 'Import products from data/products.csv'

    def handle(self, *args, **kwargs):
        file_path = os.path.join('data', 'products.csv')
        
        if not os.path.exists(file_path):
            self.stdout.write(self.style.ERROR(f'File not found: {file_path}'))
            return

        with open(file_path, mode='r', encoding='utf-8') as file:
            reader = csv.DictReader(file)
            count = 0
            for row in reader:
                Product.objects.get_or_create(
                    name=row['name'],
                    defaults={
                        'price': row['price'],
                        'category': row['category'],
                        'active': True
                    }
                )
                count += 1
        
        self.stdout.write(self.style.SUCCESS(f'Successfully imported {count} products'))
