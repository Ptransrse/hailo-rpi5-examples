import os

# Spécifie le chemin du dossier où tu veux créer le fichier
dossier = '/home/ptrans/hailo-rpi5-examples'

# Créer le dossier s'il n'existe pas déjà
if not os.path.exists(dossier):
    os.makedirs(dossier)

# Définir le chemin complet du fichier
chemin_fichier = os.path.join(dossier, 'test.txt')

# Ouvrir ou créer le fichier et y écrire du texte
with open(chemin_fichier, 'w') as fichier:
    fichier.write("ceci est un test")

print(f"Le fichier a été créé à : {chemin_fichier}")
