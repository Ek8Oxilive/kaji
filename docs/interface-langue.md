# Langue de l'interface (français / anglais)

Frontend seul, aucune route. Le sélecteur **FR | EN** est en haut de chaque page (à côté du thème ; dans la barre du haut sur téléphone). Le choix est gardé dans le navigateur (`localStorage`, clé `kaji-lang`) ; sans choix, la langue du navigateur décide (anglais si elle commence par `en`, sinon français). La page n'est pas rechargée : l'application se remonte avec la nouvelle langue (l'adresse et le cache des données restent).

## Comment ça marche
- Le **texte français du code est la clé** : `tr("Machine {name} démarrée", { name })` (`frontend/src/lib/i18n.ts`). En français, `tr` renvoie la clé ; en anglais, elle est cherchée dans `frontend/src/lib/en.json` (clé absente : le français s'affiche, jamais un trou). Le dictionnaire anglais n'est chargé que si l'anglais est choisi.
- `{nom}` est une variable : elle doit être identique dans la clé et dans la traduction.
- **Constantes de module** (tableaux, tables de libellés) : on y écrit `T("Texte")` (marqueur) et on traduit à l'affichage avec `tr(variable)` ; pour une propriété d'objet, un accesseur `get label() { return tr("Texte"); }` le fait tout seul.
- Dates et nombres : `locale()` (`fr-FR` ou `en-GB`) ; unités d'octets : `bytes()` / `mem()` (Go, Mo / GB, MB).
- La balise `<html lang>` suit la langue.

## Ajouter un texte visible (règle pour tout nouveau code)
1. Envelopper : JSX `{tr("Texte")}`, attribut `title={tr("Texte")}`, message `toast("ok", tr("Texte"))`.
2. Ajouter la traduction anglaise dans `frontend/src/lib/en.json` (clé = le français, valeur = l'anglais, mêmes `{variables}`).
3. `backend/tests/test_i18n.py` échoue sinon : clé sans traduction, variables différentes, traduction orpheline, texte JSX ou attribut resté en français brut.

## Limites connues
- Les **messages renvoyés par le serveur** (erreurs de validation et de refus de Kaji, descriptions de l'audit) restent en français : ils ne sont pas encore traduits.
- Les journaux de tâches Proxmox, les noms de machines, d'utilisateurs et de stockages sont des données : jamais traduits.
