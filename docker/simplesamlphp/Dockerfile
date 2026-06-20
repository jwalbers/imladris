FROM php:8.3-apache

# ── PHP extensions required by SimpleSAMLphp 2.x ──────────────────────────────
RUN apt-get update && apt-get install -y --no-install-recommends \
        libcurl4-openssl-dev \
        libssl-dev \
        libxml2-dev \
        libicu-dev \
        libonig-dev \
        zip unzip git curl \
    && docker-php-ext-install \
        bcmath \
        dom \
        intl \
        mbstring \
    && rm -rf /var/lib/apt/lists/*

# ── Composer ───────────────────────────────────────────────────────────────────
COPY --from=composer:latest /usr/bin/composer /usr/bin/composer

# ── Install SimpleSAMLphp 2.x via composer ────────────────────────────────────
WORKDIR /var/simplesamlphp
RUN composer create-project simplesamlphp/simplesamlphp . \
        --no-interaction --prefer-dist --no-dev

# ── Apache: enable mod_rewrite, add /simplesaml alias ─────────────────────────
RUN a2enmod rewrite

COPY apache-simplesamlphp.conf /etc/apache2/conf-enabled/simplesamlphp.conf

# ── Permissions ────────────────────────────────────────────────────────────────
RUN chown -R www-data:www-data /var/simplesamlphp

EXPOSE 80
CMD ["apache2-foreground"]
