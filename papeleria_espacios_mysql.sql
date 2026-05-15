-- ============================================================
--  PAPELERÍA ESPACIOS — Base de datos de turnos
--  Compatible con: MySQL 8+ / phpMyAdmin
--
--  Cambios respecto a la versión anterior:
--    · ticket.sesion_id es FK explícita hacia sesion.id
--    · ticket incluye columna "creado" (hora en que el cliente tomó el turno)
--    · Todas las consultas/vistas filtran por sesion_id (no por fecha)
--    · Vistas y seed actualizados en consecuencia
--
--  Importar en phpMyAdmin:
--    1. Abrir phpMyAdmin → seleccionar o crear la base "papeleria_espacios"
--    2. Pestaña "Importar" → seleccionar este archivo → Ejecutar
-- ============================================================

CREATE DATABASE IF NOT EXISTS `papeleria_espacios`
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_spanish_ci;

USE `papeleria_espacios`;


-- ────────────────────────────────────────────────────────────
-- TABLA: sesion
--   Registra cada jornada de trabajo (apertura / cierre).
--   Al iniciar una nueva jornada, el contador de turnos
--   vuelve a empezar desde 1.
-- ────────────────────────────────────────────────────────────

DROP TABLE IF EXISTS `ticket`;   -- primero ticket porque tiene FK
DROP TABLE IF EXISTS `sesion`;

CREATE TABLE `sesion` (
  `id`          INT UNSIGNED  NOT NULL AUTO_INCREMENT,
  `iniciada_en` DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP
                              COMMENT 'Momento en que el empleado inició la jornada',
  `cerrada_en`  DATETIME          NULL DEFAULT NULL
                              COMMENT 'Momento en que la jornada fue cerrada (NULL = aún activa)',
  `activa`      TINYINT(1)    NOT NULL DEFAULT 1
                              COMMENT '1 = jornada en curso, 0 = cerrada',

  PRIMARY KEY (`id`),
  KEY `idx_sesion_activa` (`activa`)

) ENGINE=InnoDB
  DEFAULT CHARSET=utf8mb4
  COLLATE=utf8mb4_spanish_ci
  COMMENT='Jornadas de trabajo. Cada jornada reinicia el contador de turnos.';


-- ────────────────────────────────────────────────────────────
-- TABLA: ticket
--   Un registro por cada turno generado.
--   `numero` se reinicia en cada jornada (por sesion_id).
--   `sesion_id` es FK explícita → sesion.id.
--
--   Estados:
--     waiting → en la cola esperando ser llamado
--     called  → ya fue llamado por el empleado, aún no atendido
--     served  → atendido y cerrado correctamente
--     missed  → cliente no se presentó / turno cancelado
-- ────────────────────────────────────────────────────────────

CREATE TABLE `ticket` (
  `id`          INT UNSIGNED      NOT NULL AUTO_INCREMENT
                                  COMMENT 'PK interna',
  `sesion_id`   INT UNSIGNED      NOT NULL
                                  COMMENT 'Jornada a la que pertenece este turno',
  `numero`      SMALLINT UNSIGNED NOT NULL
                                  COMMENT 'Número visible para el cliente (1, 2, 3… por jornada)',
  `estado`      ENUM('waiting','called','served','missed')
                                  NOT NULL DEFAULT 'waiting'
                                  COMMENT 'Estado actual del turno',
  `creado`      DATETIME          NOT NULL DEFAULT CURRENT_TIMESTAMP
                                  COMMENT 'Momento en que el cliente tomó el turno',
  `llamado_en`  DATETIME              NULL DEFAULT NULL
                                  COMMENT 'Momento en que el empleado lo llamó',
  `atendido_en` DATETIME              NULL DEFAULT NULL
                                  COMMENT 'Momento en que fue marcado como atendido o perdido',

  PRIMARY KEY (`id`),

  -- Relación con la jornada (FK explícita — igual que el modelo Python)
  CONSTRAINT `fk_ticket_sesion`
    FOREIGN KEY (`sesion_id`) REFERENCES `sesion`(`id`)
    ON DELETE CASCADE ON UPDATE CASCADE,

  -- Índices de rendimiento
  KEY `idx_ticket_sesion_estado`  (`sesion_id`, `estado`, `numero`),
  KEY `idx_ticket_creado`         (`creado`),

  -- Número único dentro de la misma jornada
  UNIQUE KEY `uq_ticket_sesion_numero` (`sesion_id`, `numero`)

) ENGINE=InnoDB
  DEFAULT CHARSET=utf8mb4
  COLLATE=utf8mb4_spanish_ci
  COMMENT='Turnos generados por los clientes. Cada jornada tiene su propio contador.';


-- ────────────────────────────────────────────────────────────
-- VISTAS ÚTILES
-- ────────────────────────────────────────────────────────────

-- Cola activa: turnos pendientes en la jornada en curso
-- Filtra por sesion_id (no por fecha) para mayor precisión
DROP VIEW IF EXISTS `v_cola_activa`;
CREATE VIEW `v_cola_activa` AS
  SELECT
    t.id,
    t.sesion_id,
    t.numero,
    t.estado,
    t.creado,
    t.llamado_en,
    TIMESTAMPDIFF(MINUTE, t.creado, NOW()) AS minutos_espera
  FROM ticket t
  INNER JOIN sesion s ON s.id = t.sesion_id
  WHERE s.activa = 1
    AND t.estado IN ('waiting', 'called')
  ORDER BY t.numero ASC;


-- Resumen de la jornada activa
DROP VIEW IF EXISTS `v_resumen_jornada`;
CREATE VIEW `v_resumen_jornada` AS
  SELECT
    s.id                                                      AS sesion_id,
    s.iniciada_en,
    COUNT(t.id)                                               AS total_turnos,
    SUM(t.estado = 'served')                                  AS atendidos,
    SUM(t.estado = 'missed')                                  AS perdidos,
    SUM(t.estado IN ('waiting','called'))                     AS en_espera,
    ROUND(AVG(
      CASE WHEN t.estado = 'served' AND t.llamado_en IS NOT NULL
           THEN TIMESTAMPDIFF(SECOND, t.creado, t.atendido_en) / 60.0
      END
    ), 1)                                                     AS promedio_min_total,
    ROUND(AVG(
      CASE WHEN t.estado = 'served' AND t.llamado_en IS NOT NULL
           THEN TIMESTAMPDIFF(SECOND, t.llamado_en, t.atendido_en) / 60.0
      END
    ), 1)                                                     AS promedio_min_atencion
  FROM sesion s
  LEFT JOIN ticket t ON t.sesion_id = s.id
  WHERE s.activa = 1
  GROUP BY s.id, s.iniciada_en;


-- Reporte de cierre: turnos de la última jornada cerrada
DROP VIEW IF EXISTS `v_reporte_ultima_jornada`;
CREATE VIEW `v_reporte_ultima_jornada` AS
  SELECT
    t.numero,
    t.estado,
    TIME(t.creado)      AS hora_creacion,
    TIME(t.llamado_en)  AS hora_llamado,
    TIME(t.atendido_en) AS hora_fin,
    TIMESTAMPDIFF(SECOND, t.creado,     t.atendido_en) AS segundos_espera_total,
    TIMESTAMPDIFF(SECOND, t.llamado_en, t.atendido_en) AS segundos_atencion
  FROM ticket t
  INNER JOIN sesion s ON s.id = t.sesion_id
  WHERE s.activa = 0
    AND s.cerrada_en = (SELECT MAX(cerrada_en) FROM sesion WHERE activa = 0)
  ORDER BY t.numero ASC;


-- Histórico completo por jornada
DROP VIEW IF EXISTS `v_historico_jornadas`;
CREATE VIEW `v_historico_jornadas` AS
  SELECT
    s.id                          AS sesion_id,
    DATE(s.iniciada_en)           AS dia,
    TIME(s.iniciada_en)           AS hora_inicio,
    TIME(s.cerrada_en)            AS hora_cierre,
    s.activa,
    COUNT(t.id)                   AS total_turnos,
    SUM(t.estado = 'served')      AS atendidos,
    SUM(t.estado = 'missed')      AS perdidos,
    SUM(t.estado IN ('waiting','called')) AS en_espera
  FROM sesion s
  LEFT JOIN ticket t ON t.sesion_id = s.id
  GROUP BY s.id, s.iniciada_en, s.cerrada_en, s.activa
  ORDER BY s.id DESC;


-- ────────────────────────────────────────────────────────────
-- DATOS DE EJEMPLO (seed)
--   Simula una mañana completa: jornada cerrada + jornada activa
-- ────────────────────────────────────────────────────────────

-- Jornada de ayer (ya cerrada) — sesion_id = 1
INSERT INTO `sesion` (`iniciada_en`, `cerrada_en`, `activa`) VALUES
  (DATE_SUB(NOW(), INTERVAL 25 HOUR),
   DATE_SUB(NOW(), INTERVAL 17 HOUR),
   0);

-- Turnos de ayer (sesion_id = 1)
INSERT INTO `ticket`
  (`sesion_id`, `numero`, `estado`, `creado`, `llamado_en`, `atendido_en`)
VALUES
  (1, 1, 'served',
   DATE_SUB(NOW(), INTERVAL 24    HOUR),
   DATE_SUB(NOW(), INTERVAL 23    HOUR),
   DATE_SUB(NOW(), INTERVAL 22    HOUR)),
  (1, 2, 'served',
   DATE_SUB(NOW(), INTERVAL 1430  MINUTE),
   DATE_SUB(NOW(), INTERVAL 1365  MINUTE),
   DATE_SUB(NOW(), INTERVAL 1350  MINUTE)),
  (1, 3, 'missed',
   DATE_SUB(NOW(), INTERVAL 1350  MINUTE),
   DATE_SUB(NOW(), INTERVAL 1315  MINUTE),
   DATE_SUB(NOW(), INTERVAL 1314  MINUTE));


-- Jornada de hoy (activa) — sesion_id = 2
INSERT INTO `sesion` (`iniciada_en`, `cerrada_en`, `activa`) VALUES
  (DATE_SUB(NOW(), INTERVAL 3 HOUR), NULL, 1);

-- Turnos de hoy (sesion_id = 2)
INSERT INTO `ticket`
  (`sesion_id`, `numero`, `estado`, `creado`, `llamado_en`, `atendido_en`)
VALUES
  (2, 1, 'served',
   DATE_SUB(NOW(), INTERVAL 170 MINUTE),
   DATE_SUB(NOW(), INTERVAL 165 MINUTE),
   DATE_SUB(NOW(), INTERVAL 158 MINUTE)),
  (2, 2, 'served',
   DATE_SUB(NOW(), INTERVAL 155 MINUTE),
   DATE_SUB(NOW(), INTERVAL 150 MINUTE),
   DATE_SUB(NOW(), INTERVAL 140 MINUTE)),
  (2, 3, 'missed',
   DATE_SUB(NOW(), INTERVAL 138 MINUTE),
   DATE_SUB(NOW(), INTERVAL 130 MINUTE),
   DATE_SUB(NOW(), INTERVAL 129 MINUTE)),
  (2, 4, 'served',
   DATE_SUB(NOW(), INTERVAL 125 MINUTE),
   DATE_SUB(NOW(), INTERVAL 118 MINUTE),
   DATE_SUB(NOW(), INTERVAL 108 MINUTE)),
  (2, 5, 'called',
   DATE_SUB(NOW(), INTERVAL 40  MINUTE),
   DATE_SUB(NOW(), INTERVAL 5   MINUTE),
   NULL),
  (2, 6, 'waiting',
   DATE_SUB(NOW(), INTERVAL 20  MINUTE),
   NULL, NULL),
  (2, 7, 'waiting',
   DATE_SUB(NOW(), INTERVAL 10  MINUTE),
   NULL, NULL),
  (2, 8, 'waiting',
   DATE_SUB(NOW(), INTERVAL 3   MINUTE),
   NULL, NULL);


-- ────────────────────────────────────────────────────────────
-- CONSULTAS DE REFERENCIA
-- (copiar y pegar en phpMyAdmin o usar desde la aplicación)
-- ────────────────────────────────────────────────────────────

-- ► Ver jornada activa
-- SELECT * FROM sesion WHERE activa = 1 LIMIT 1;

-- ► Ver cola en vivo (usando la vista)
-- SELECT * FROM v_cola_activa;

-- ► Siguiente turno a llamar
-- SELECT * FROM ticket
-- WHERE sesion_id = (SELECT id FROM sesion WHERE activa = 1 LIMIT 1)
--   AND estado = 'waiting'
-- ORDER BY numero ASC LIMIT 1;

-- ► Llamar al siguiente turno
-- UPDATE ticket
-- SET estado = 'called', llamado_en = NOW()
-- WHERE sesion_id = (SELECT id FROM sesion WHERE activa = 1 LIMIT 1)
--   AND estado = 'waiting'
-- ORDER BY numero ASC LIMIT 1;

-- ► Marcar turno actual como atendido
-- UPDATE ticket
-- SET estado = 'served', atendido_en = NOW()
-- WHERE sesion_id = (SELECT id FROM sesion WHERE activa = 1 LIMIT 1)
--   AND estado = 'called'
-- ORDER BY llamado_en DESC LIMIT 1;

-- ► Marcar turno actual como perdido
-- UPDATE ticket
-- SET estado = 'missed', atendido_en = NOW()
-- WHERE sesion_id = (SELECT id FROM sesion WHERE activa = 1 LIMIT 1)
--   AND estado = 'called'
-- ORDER BY llamado_en DESC LIMIT 1;

-- ► Cerrar jornada (marcar pendientes como perdidos y cerrar sesión)
-- UPDATE ticket
-- SET estado = 'missed', atendido_en = NOW()
-- WHERE sesion_id = (SELECT id FROM sesion WHERE activa = 1 LIMIT 1)
--   AND estado IN ('waiting', 'called');
--
-- UPDATE sesion SET activa = 0, cerrada_en = NOW() WHERE activa = 1;

-- ► Iniciar nueva jornada
-- UPDATE sesion SET activa = 0, cerrada_en = NOW() WHERE activa = 1;
-- INSERT INTO sesion (iniciada_en, activa) VALUES (NOW(), 1);

-- ► Resumen de la jornada activa (usando la vista)
-- SELECT * FROM v_resumen_jornada;

-- ► Reporte de la última jornada cerrada (usando la vista)
-- SELECT * FROM v_reporte_ultima_jornada;

-- ► Histórico de todas las jornadas
-- SELECT * FROM v_historico_jornadas;

-- ► Posición en la cola de un turno específico
-- SELECT COUNT(*) + 1 AS posicion
-- FROM ticket
-- WHERE sesion_id = :sesion_id
--   AND estado = 'waiting'
--   AND numero < :mi_numero;

-- ► Todos los turnos de una sesión específica (igual que hace el Python)
-- SELECT * FROM ticket
-- WHERE sesion_id = :sesion_id
-- ORDER BY numero ASC;

-- ► Próximo número de turno disponible en la jornada activa
-- SELECT COALESCE(MAX(numero), 0) + 1 AS proximo
-- FROM ticket
-- WHERE sesion_id = (SELECT id FROM sesion WHERE activa = 1 LIMIT 1);
