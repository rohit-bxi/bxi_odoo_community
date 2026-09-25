-- never talk to HDFC from a neutralized (copied) database
UPDATE hdfc_bank_config
   SET environment = 'mock',
       base_url = NULL,
       client_secret = NULL,
       api_key = NULL;

DELETE FROM ir_attachment
 WHERE res_model = 'hdfc.bank.config'
   AND res_field IN ('client_private_key', 'client_certificate', 'bank_public_certificate');

-- stop the status sync so mock results never land on copied production batches
UPDATE ir_cron
   SET active = false
 WHERE id IN (
     SELECT res_id FROM ir_model_data
      WHERE module = 'bxi_hdfc_payroll'
        AND model = 'ir.cron'
        AND name = 'ir_cron_hdfc_sync_status'
 );
