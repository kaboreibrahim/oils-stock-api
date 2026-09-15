"""Chargé avant toute config Django (dès `import core.settings`) — nécessaire
pour que le backend MySQL de Django (qui importe `MySQLdb`, l'extension C
`mysqlclient`) fonctionne avec PyMySQL à la place. Choisi plutôt que
`mysqlclient` car pur Python : aucune compilation nécessaire, donc utilisable
tel quel sur un hébergement mutualisé sans compilateur C ni accès root — voir
`core/settings.py::DATABASES` (production uniquement, le dev reste sur
PostgreSQL/psycopg, qui n'a pas besoin de ce shim)."""

import pymysql

pymysql.install_as_MySQLdb()