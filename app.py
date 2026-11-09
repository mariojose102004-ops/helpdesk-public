# D:\public\app.py  (projet PUBLIC uniquement — sans login ni portal)
import os
import secrets
import string
from datetime import datetime

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv
from flask import (Flask, render_template, request, redirect, url_for,
                   flash, g)
from werkzeug.utils import secure_filename

load_dotenv()

BASE_DIR = os.path.abspath(os.path.dirname(__file__))

app = Flask(
    __name__,
    template_folder=os.path.join(BASE_DIR, "templates"),
    static_folder=os.path.join(BASE_DIR, "static"),
)
app.secret_key = os.getenv("SECRET_KEY", "changez-moi")

UPLOAD_FOLDER = os.path.join(BASE_DIR, "static", "uploads")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["MAX_CONTENT_LENGTH"] = 6 * 1024 * 1024  # 6 Mo


# ============================================================
# CONNEXION POSTGRESQL
# ============================================================
def get_db():
    """Retourne une connexion PostgreSQL (une par requête)."""
    if "db" not in g:
        g.db = psycopg2.connect(
            host=os.getenv("DB_HOST", "localhost"),
            port=os.getenv("DB_PORT", "5432"),
            dbname=os.getenv("DB_NAME", "helpdesk"),
            user=os.getenv("DB_USER", "postgres"),
            password=os.getenv("DB_PASSWORD", ""),
            client_encoding="UTF8",  # évite l'UnicodeDecodeError sous Windows
        )
    return g.db


@app.teardown_appcontext
def close_db(exception=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


# ============================================================
# HELPERS
# ============================================================
def generer_numero_ticket():
    """Génère un numéro unique et difficile à deviner : TCK-20261102-A7K9X2M4."""
    code = ''.join(
        secrets.choice(string.ascii_uppercase + string.digits)
        for _ in range(8)
    )
    return f"TCK-{datetime.now():%Y%m%d}-{code}"


def sauver_photo(fichier):
    """Sauvegarde la photo et retourne son nom de fichier, ou None."""
    if not fichier or not fichier.filename:
        return None

    # Vérifier la taille (5 Mo max)
    fichier.seek(0, os.SEEK_END)
    taille = fichier.tell()
    fichier.seek(0)
    if taille > 5 * 1024 * 1024:
        return "ERREUR_TAILLE"

    # Vérifier l'extension
    ext = os.path.splitext(secure_filename(fichier.filename))[1].lower()
    if ext not in {".jpg", ".jpeg", ".png"}:
        return "ERREUR_FORMAT"

    # Nom unique basé sur le timestamp + code aléatoire
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    alea = ''.join(secrets.choice(string.ascii_lowercase + string.digits)
                   for _ in range(6))
    nom_fichier = f"demande_{timestamp}_{alea}{ext}"
    fichier.save(os.path.join(app.config["UPLOAD_FOLDER"], nom_fichier))
    return nom_fichier


# ============================================================
# ROUTES PUBLIQUES
# ============================================================
@app.route("/")
def accueil():
    return redirect(url_for("nouvelle_demande"))


@app.route("/demande", methods=["GET", "POST"])
def nouvelle_demande():
    if request.method == "POST":
        # Récupération des champs
        nom = request.form.get("nom", "").strip()
        email = request.form.get("email", "").strip()
        service = request.form.get("service", "").strip()
        numero_bureau = request.form.get("numero_bureau", "").strip()
        sujet = request.form.get("sujet", "").strip()
        description = request.form.get("description", "").strip()
        categories = request.form.getlist("categories")

        # Validation minimale
        if not (nom and email and numero_bureau and sujet and description):
            flash("Tous les champs obligatoires doivent être remplis.", "error")
            return render_template("public/nouvelle_demande.html"), 400

        if not categories:
            flash("Veuillez cocher au moins une catégorie.", "error")
            return render_template("public/nouvelle_demande.html"), 400

        # Gestion de la photo (optionnelle)
        photo_filename = None
        photo = request.files.get("photo_probleme")
        if photo and photo.filename:
            resultat = sauver_photo(photo)
            if resultat == "ERREUR_TAILLE":
                flash("La photo dépasse 5 Mo.", "error")
                return render_template("public/nouvelle_demande.html"), 400
            if resultat == "ERREUR_FORMAT":
                flash("Format d'image non accepté (JPG/PNG uniquement).", "error")
                return render_template("public/nouvelle_demande.html"), 400
            photo_filename = resultat

        # Insertion en base
        numero = generer_numero_ticket()
        conn = get_db()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO demande
                      (numero_ticket, demandeur_nom, demandeur_email,
                       demandeur_service, numero_bureau, titre, probleme,
                       categories, image, statut, date_demande)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,'en_attente',NOW())
                    """,
                    (numero, nom, email, service, numero_bureau,
                     sujet, description, ",".join(categories), photo_filename),
                )
            conn.commit()
        except Exception:
            conn.rollback()
            app.logger.exception("Erreur lors de l'insertion du ticket")
            flash("Une erreur est survenue lors de l'envoi. Réessayez.", "error")
            return render_template("public/nouvelle_demande.html"), 500

        flash(f"Votre demande a été envoyée. Numéro de ticket : {numero}", "success")
        # Redirection vers /suivi avec le numéro uniquement (plus d'email)
        return redirect(url_for("suivi", numero=numero))

    return render_template("public/nouvelle_demande.html")


@app.route("/suivi", methods=["GET", "POST"])
def suivi():
    demande = None

    # Pré-remplissage possible depuis la query string après une création
    if request.method == "GET":
        numero = request.args.get("numero", "").strip()
        if numero:
            demande = _rechercher_demande(numero)

    if request.method == "POST":
        numero = request.form.get("numero", "").strip()
        if numero:
            demande = _rechercher_demande(numero)
            if not demande:
                flash("Aucune demande trouvée avec ce numéro de ticket.", "warning")
        else:
            flash("Veuillez renseigner le numéro de ticket.", "warning")

    return render_template("public/suivi.html", demande=demande)


def _rechercher_demande(numero):
    """Recherche un ticket par son numéro unique. Retourne un dict ou None."""
    conn = get_db()
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            "SELECT * FROM demande WHERE numero_ticket=%s",
            (numero,),
        )
        return cur.fetchone()


# ============================================================
# POINT D'ENTRÉE
# ============================================================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5050, debug=True)