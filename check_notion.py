from notion_client import Client
c = Client(auth='test')
print([m for m in dir(c.databases) if not m.startswith('_')])
