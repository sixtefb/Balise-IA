"""Couche réservée aux données transmises par le client (non implémentée à ce stade).

Cette couche accueillera, dans une étape ultérieure, la comptabilité
détaillée ou d'autres documents fournis par la commune auditée. Elle reste
séparée de la couche "public benchmark" (balise.models.CommuneIdentity et
balise.ingestion.*) : les données client se comparent au benchmark public,
elles n'y contribuent jamais.
"""
