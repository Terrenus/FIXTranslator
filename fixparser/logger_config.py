import logging
import sys
from pythonjsonlogger import json

def setup_logging():
    """Configures application logging to output in JSON format."""
    
    formatter = json.JsonFormatter(
        '%(asctime)s %(levelname)s %(name)s %(message)s',
        rename_fields={
            'asctime': 'timestamp',
            'levelname': 'level',
            'name': 'logger_name',
            'message': 'message'
        }
    )

    log_handler = logging.StreamHandler(sys.stdout)
    log_handler.setFormatter(formatter)
    
    root_logger = logging.getLogger()

    if root_logger.handlers:
        root_logger.handlers.clear()
    

    root_logger.setLevel(logging.INFO)
    root_logger.addHandler(log_handler)
    
    logging.getLogger("uvicorn.access").handlers.clear()
    
    return logging.getLogger("fixparser")

logger = setup_logging()