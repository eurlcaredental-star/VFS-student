# 🚂 Déploiement Railway — VFS Italy Monitor Bot

## Pourquoi Railway ?

Replit gratuit **s'arrête** après 1h d'inactivité. Pour que le bot tourne **h24/7j**, il faut le migrer sur Railway qui offre :
- ✅ 500 heures gratuites/mois (suffisant pour 1 bot)
- ✅ Redémarrage automatique en cas de crash
- ✅ Persistance des données
- ✅ Variables d'environnement sécurisées

---

## Étape 1 : Créer un compte Railway

1. Va sur [railway.app](https://railway.app)
2. Clique **"Start a New Project"**
3. Connecte ton compte GitHub

---

## Étape 2 : Pousser le code sur GitHub

```bash
# Dans ton terminal Replit
cd /home/runner/workspace
git init
git add bot/
git commit -m "VFS Italy Monitor Bot"
git remote add origin https://github.com/TON_USER/vfs-italy-bot.git
git push -u origin main
```

---

## Étape 3 : Créer le service Railway

1. Sur Railway → **"New Project" → "Deploy from GitHub Repo"**
2. Sélectionne ton repo
3. Railway détecte automatiquement le **Dockerfile**

---

## Étape 4 : Variables d'environnement

Dans Railway → ton projet → **"Variables"** → Ajoute :

```
TELEGRAM_BOT_TOKEN = 8634149640:AAFAxYZRlSeQ-Y_uk_qhLGB_tMSzCcMScPY
VFS_EMAIL = Eurlcaredental@gmail.com
VFS_PASSWORD = Aness26032001.
DB_PATH = /app/data/vfs_bot.db
CHECK_INTERVAL = 120
```

---

## Étape 5 : Volume persistant (important!)

Pour que la base de données survive aux redémarrages :

1. Railway → ton service → **"Volumes"**
2. Ajoute un volume sur `/app/data`
3. Taille : 1 GB (gratuit)

---

## Étape 6 : Deploy !

Railway déploie automatiquement. Le bot devrait démarrer en 2-3 minutes.

---

## 🔍 Vérifier que ça marche

Sur Telegram, tape `/verify` — le bot affichera :
- ✅ Base de données OK
- ✅ Connexion VFS OK  
- ✅ Planificateur OK

---

## 💡 Tips Railway

- Le bot redémarre automatiquement s'il crash
- Les logs sont visibles dans Railway dashboard
- Plan gratuit = 500h/mois = suffisant pour 1 mois complet

**Lien direct Railway :** https://railway.app/new
