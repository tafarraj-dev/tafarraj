import os
import django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'dramahere.settings')
django.setup()
from django.db import connection
cursor = connection.cursor()
cursor.execute("DELETE FROM django_migrations WHERE app = 'Tafarraj'")
connection.connection.commit()
print('done')