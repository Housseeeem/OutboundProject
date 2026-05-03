import requests
from bs4 import BeautifulSoup
import re

def extraire_donnees_page(url: str) -> dict:
    """
    Aspire la page web ET cherche automatiquement les emails/téléphones.
    Retourne un dictionnaire avec le texte, et les contacts trouvés.
    """
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/91.0'
        }
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()

        soup = BeautifulSoup(response.text, 'html.parser')
        elements = soup.find_all(['p', 'h1', 'h2', 'h3', 'li'])
        texte_nettoye = " ".join([elem.get_text(strip=True) for elem in elements])
        texte_final = texte_nettoye[:2500] # On garde 2500 caractères

        # 🕵️‍♂️ Recherche automatique d'emails avec une Regex
        emails_trouves = re.findall(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', texte_final)
        
        # 🕵️‍♂️ Recherche automatique de numéros (format basique)
        telephones_trouves = re.findall(r'(?:(?:\+|00)33|0)\s*[1-9](?:[\s.-]*\d{2}){4}', texte_final)

        return {
            "texte": texte_final,
            "has_email": len(emails_trouves) > 0,
            "has_phone": len(telephones_trouves) > 0,
            "emails": emails_trouves,
            "phones": telephones_trouves
        }
        
    except Exception as e:
        return {"error": f"Erreur d'extraction : {e}"}