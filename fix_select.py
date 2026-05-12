with open("tests/test_conversations.py", "r") as f:
    content = f.read()

content = content.replace("from sqlalchemy.orm import Session", "from sqlalchemy.orm import Session\nfrom sqlalchemy import select")
content = content.replace("s.query(Task)", "select(Task)")

with open("tests/test_conversations.py", "w") as f:
    f.write(content)
