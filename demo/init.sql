CREATE TABLE campaign (
    id BIGINT PRIMARY KEY,
    initial_stock INT NOT NULL,
    stock INT NOT NULL
) ENGINE=InnoDB;

CREATE TABLE issued_coupon (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    campaign_id BIGINT NOT NULL,
    user_id VARCHAR(64) NOT NULL,
    request_id VARCHAR(64) NOT NULL,
    UNIQUE KEY one_per_user (campaign_id, user_id),
    UNIQUE KEY one_per_request (request_id)
) ENGINE=InnoDB;

INSERT INTO campaign (id, initial_stock, stock) VALUES (1, 20, 20);
