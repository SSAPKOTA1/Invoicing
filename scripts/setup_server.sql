-- Einrichtung des PostgreSQL-Servers für den Mehrbenutzer-Betrieb (Lieferantenkonto & Mahnungs-Tracker).
-- Ausführen als Datenbank-Administrator, z. B.:
--     psql -U postgres -f setup_server.sql
-- VORHER das Passwort unten ändern!

CREATE ROLE supplierapp LOGIN PASSWORD 'HIER-EIN-LANGES-PASSWORT-EINTRAGEN';
CREATE DATABASE supplierapp OWNER supplierapp ENCODING 'UTF8';

-- Der Benutzer "supplierapp" legt das Schema beim ersten Start selbst an (Tabellen, Trigger, Suchindex)
-- und braucht dafür keine Administratorrechte.
