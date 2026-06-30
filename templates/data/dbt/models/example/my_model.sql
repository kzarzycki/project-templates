-- Example model. Replace with your own.
{{ config(materialized="view") }}

select
    1 as id,
    'hello' as message
