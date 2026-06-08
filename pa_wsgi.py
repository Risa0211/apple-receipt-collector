import os
import sys

project_home = "/home/eight0808/apple-receipt-collector"
if project_home not in sys.path:
    sys.path.insert(0, project_home)

from dotenv import load_dotenv
load_dotenv(os.path.join(project_home, ".env"))

from app import app as application
