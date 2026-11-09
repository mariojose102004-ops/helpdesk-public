import psycopg2
from werkzeug.security import generate_password_hash

DB = dict(host="localhost", port=5432, dbname="helpdesk",
          user="postgres", password="rakotomahefa")

conn = psycopg2.connect(**DB)
cur = conn.cursor()

with open("schema.sql", "r", encoding="utf-8") as f:
    cur.execute(f.read())

cur.execute("""
    INSERT INTO utilisateur (nom, prenom, telephone, email, username,
                             mot_de_passe, role, valide)
    VALUES (%s,%s,%s,%s,%s,%s,'admin',TRUE)
    ON CONFLICT (username) DO NOTHING
""", ("Admin", "Système", "0000000000", "admin@ministere.cm",
      "admin", generate_password_hash("admin123")))

conn.commit()
cur.close()
conn.close()
print("Base initialisée ✔  (admin / admin123)")