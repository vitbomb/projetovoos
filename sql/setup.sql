-- -------------------------------------------------------------
-- 1. Criação da tabela public.voos
-- -------------------------------------------------------------
CREATE TABLE public.voos (
    -- Identificador único do registro (auto‑incremento)
    id             BIGSERIAL PRIMARY KEY,

    -- Data de referência do voo (ex.: 2024‑09‑17)
    data_referencia DATE NOT NULL,

    -- Código ICAO da empresa (ex.: AAL)
    codigo_icao_empresa CHAR(3) NOT NULL,

    -- Número do voo (ex.: 1234)
    numero_voo     VARCHAR(10) NOT NULL,

    -- Etapa do voo (ex.: "A", "B", "C")
    etapa           VARCHAR(50) NOT NULL,

    -- Código ICAO do aeroporto de origem (ex.: SBGR)
    aeroporto_icao_origem CHAR(4) NOT NULL,

    -- Código ICAO do aeroporto de destino (ex.: SBFL)
    aeroporto_icao_destino CHAR(4) NOT NULL,

    -- Horário previsto de partida (com fuso horário)
    horario_previsto_partida TIMESTAMP WITH TIME ZONE,

    -- Horário previsto de chegada (com fuso horário)
    horario_previsto_chegada TIMESTAMP WITH TIME ZONE,

    -- Equipamento (ex.: B737, A320)
    equipamento    VARCHAR(20),

    -- Quantidade de assentos no avião
    quantidade_assentos INTEGER,

    -- Tipo de operação (ex.: "Comercial", "Militar")
    tipo_operacao  VARCHAR(50),

    -- Tipo de serviço (ex.: "Passageiro", "Cargas")
    tipo_servico   VARCHAR(50),

    -- Data de inserção (automática)
    data_insercao  TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),

    -- Data de atualização (atualizada automaticamente)
    data_atualizacao TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now()
);

-- -------------------------------------------------------------
-- 2. Trigger para atualizar data_atualizacao em cada UPDATE
-- -------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.update_data_atualizacao()
RETURNS TRIGGER AS $$BEGIN
    NEW.data_atualizacao = now();
    RETURN NEW;
END;$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_update_data_atualizacao
BEFORE UPDATE ON public.voos
FOR EACH ROW EXECUTE FUNCTION public.update_data_atualizacao();

-- -------------------------------------------------------------
-- 3. Constraint UNIQUE para evitar voos duplicados
-- -------------------------------------------------------------
-- Garante que não existam registros iguais quanto a
-- data, companhia, número de voo, etapa, origem e destino.
ALTER TABLE public.voos ADD CONSTRAINT voos_unico UNIQUE (
    data_referencia,
    codigo_icao_empresa,
    numero_voo,
    etapa,
    aeroporto_icao_origem,
    aeroporto_icao_destino,
    horario_previsto_partida
);

-- -------------------------------------------------------------
-- 4. Índices para acelerar consultas por data, origem e destino
-- -------------------------------------------------------------
CREATE INDEX idx_voos_data_referencia ON public.voos (data_referencia);
CREATE INDEX idx_voos_aeroporto_origem ON public.voos (aeroporto_icao_origem);
CREATE INDEX idx_voos_aeroporto_destino ON public.voos (aeroporto_icao_destino);

-- -------------------------------------------------------------
-- 5. Habilitar Row Level Security (RLS)
-- -------------------------------------------------------------
ALTER TABLE public.voos ENABLE ROW LEVEL SECURITY;

-- -------------------------------------------------------------
-- 6. Política de acesso público somente leitura
-- -------------------------------------------------------------
CREATE POLICY p_public_read ON public.voos
FOR SELECT
USING (true);   -- todas as linhas são visíveis

-- -------------------------------------------------------------
-- 7. Concessão de privilégios
-- -------------------------------------------------------------
-- 7a. SELECT para usuários anon e authenticated
GRANT SELECT ON public.voos TO anon;
GRANT SELECT ON public.voos TO authenticated;

-- 7b. ALL (INSERT, UPDATE, DELETE, etc.) para service_role
GRANT ALL PRIVILEGES ON public.voos TO service_role;

-- -------------------------------------------------------------
-- Fim da configuração do banco
-- -------------------------------------------------------------