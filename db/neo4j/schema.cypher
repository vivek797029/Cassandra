// ARGUS — Temporal Causal Knowledge Graph schema (Neo4j 5.x)
// Apply: cypher-shell -f db/neo4j/schema.cypher
// Node keys ------------------------------------------------------------------
CREATE CONSTRAINT actor_id    IF NOT EXISTS FOR (a:Actor)     REQUIRE a.id IS UNIQUE;
CREATE CONSTRAINT event_id    IF NOT EXISTS FOR (e:Event)     REQUIRE e.id IS UNIQUE;
CREATE CONSTRAINT loc_h3      IF NOT EXISTS FOR (l:Location)  REQUIRE l.h3 IS UNIQUE;
CREATE CONSTRAINT var_key     IF NOT EXISTS FOR (v:Variable)  REQUIRE v.key IS UNIQUE;
CREATE CONSTRAINT claim_id    IF NOT EXISTS FOR (c:Claim)     REQUIRE c.id IS UNIQUE;
CREATE CONSTRAINT source_id   IF NOT EXISTS FOR (s:Source)    REQUIRE s.id IS UNIQUE;
CREATE CONSTRAINT mech_id     IF NOT EXISTS FOR (m:Mechanism) REQUIRE m.id IS UNIQUE;
CREATE CONSTRAINT case_id     IF NOT EXISTS FOR (k:Case)      REQUIRE k.id IS UNIQUE;
CREATE CONSTRAINT policy_id   IF NOT EXISTS FOR (p:Policy)    REQUIRE p.id IS UNIQUE;
CREATE CONSTRAINT narrative_id IF NOT EXISTS FOR (n:Narrative) REQUIRE n.id IS UNIQUE;
CREATE INDEX event_time IF NOT EXISTS FOR (e:Event) ON (e.occurred_at);
CREATE INDEX fact_valid IF NOT EXISTS FOR (c:Claim) ON (c.valid_from, c.valid_to);

// Node shapes (documented; Neo4j is schema-flexible) -------------------------
// (:Actor      {id, name, kind: state|org|leader|group, attrs})
// (:Event      {id, type, occurred_at, magnitude, confidence})
// (:Location   {h3, name, admin, lat, lon})
// (:Variable   {key, name, unit, domain})            // e.g. brent_usd, infl_global
// (:Claim      {id, text, valid_from, valid_to, tx_time, confidence})
// (:Source     {id, name, reliability_alpha, reliability_beta})  // Beta posterior
// (:Mechanism  {id, form, params_json, id_status: identified|estimated|expert|hypothesis,
//               lag_q, sign, score_history_json})    // REIFIED causal edge (blueprint §5)
// (:Case       {id, name, period, similarity_features_json})
// (:Policy     {id, name, handles_json, cost, legality_tags})
// (:Narrative  {id, text, first_seen, reach_index, coordination_score})  // info-domain (defensive)

// Relationships ----------------------------------------------------------------
// (a:Actor)-[:PARTICIPATED_IN {role}]->(e:Event)
// (e:Event)-[:LOCATED_AT]->(l:Location)
// (c:Claim)-[:ABOUT]->(e:Event)  (c)-[:FROM_SOURCE]->(s:Source)
// (c1:Claim)-[:SUPPORTS|CONTRADICTS]->(c2:Claim)
// (m:Mechanism)-[:FROM_VAR]->(v1:Variable)  (m)-[:TO_VAR]->(v2:Variable)
// (e:Event)-[:EVIDENCES {weight}]->(m:Mechanism)
// (k:Case)-[:INSTANTIATES]->(m:Mechanism)
// (k1:Case)-[:ANALOG_OF {similarity}]->(k2:Case)
// (p:Policy)-[:TARGETS]->(m:Mechanism)

// Seed: load the prototype micro-graph (idempotent) ---------------------------
MERGE (me:Variable {key:'me_regime'})   SET me.name='Middle East conflict regime', me.domain='security';
MERGE (oil:Variable {key:'brent_usd'})  SET oil.name='Brent crude', oil.unit='USD/bbl', oil.domain='economic';
MERGE (inf:Variable {key:'infl_global'}) SET inf.name='Global headline inflation', inf.unit='%', inf.domain='economic';
MERGE (g:Variable {key:'growth_global'}) SET g.name='Global GDP growth', g.unit='%', g.domain='economic';
MERGE (fd:Variable {key:'food_idx'})    SET fd.name='Food price index', fd.domain='environmental';
MERGE (em:Variable {key:'em_defaults'}) SET em.name='EM default events', em.domain='economic';

MERGE (m1:Mechanism {id:'me_war__oil'})
  SET m1.form='regime_anchor_jump', m1.id_status='identified',
      m1.sign=1, m1.lag_q=0,
      m1.params_json='{"war_anchor":112,"hormuz_anchor":138,"jump_war":1.24,"jump_hormuz":1.39}';
MERGE (m1)-[:FROM_VAR]->(me) MERGE (m1)-[:TO_VAR]->(oil);

MERGE (m2:Mechanism {id:'oil__inflation'})
  SET m2.form='linear_passthrough_above_80', m2.id_status='estimated',
      m2.sign=1, m2.lag_q=1, m2.params_json='{"coef_pp_per_usd":0.024}';
MERGE (m2)-[:FROM_VAR]->(oil) MERGE (m2)-[:TO_VAR]->(inf);

MERGE (m3:Mechanism {id:'oil__growth'})
  SET m3.form='linear_drag_above_80', m3.id_status='estimated',
      m3.sign=-1, m3.lag_q=1, m3.params_json='{"coef_pp_per_usd":0.018}';
MERGE (m3)-[:FROM_VAR]->(oil) MERGE (m3)-[:TO_VAR]->(g);

MERGE (m4:Mechanism {id:'food__em_stress'})
  SET m4.form='hazard_increment', m4.id_status='expert',
      m4.sign=1, m4.lag_q=2, m4.params_json='{"infl_coef":0.004,"growth_coef":0.006}';
MERGE (m4)-[:FROM_VAR]->(fd) MERGE (m4)-[:TO_VAR]->(em);
