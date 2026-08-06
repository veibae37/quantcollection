# coding:utf-8
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
import talib

def init(ContextInfo):
    ContextInfo.my_holding = False 
    ContextInfo.train_len = 100       
    ContextInfo.predict_lag = 1       
    ContextInfo.rebalance_freq = 20   
    
    ContextInfo.clf = RandomForestClassifier(n_estimators=50, max_depth=4, random_state=42)
    ContextInfo.bar_idx = 0
    ContextInfo.is_trained = False
    print("?? ���Գ�ʼ����ɣ��ȴ���ʷK�߼���...")

def handlebar(ContextInfo):
    ContextInfo.bar_idx += 1
    stock = ContextInfo.stockcode 
def handlebar(ContextInfo):
    ContextInfo.bar_idx += 1
    
    # 1. ��ȡ�Ҳ�����ԭʼ���� (������ '000001')
    raw_stock = ContextInfo.stockcode 
    
    # ?? ���Ĳ������Զ�Ϊ������� .SZ �� .SH ��׺P
    if '.' not in raw_stock:
        if str(raw_stock).startswith('6'):
            stock = str(raw_stock) + '.SH'   # ����
        elif str(raw_stock).startswith('8') or str(raw_stock).startswith('4'):
            stock = str(raw_stock) + '.BJ'   # ������
        else:
            stock = str(raw_stock) + '.SZ'   # ����
    else:
        stock = raw_stock  # ����Ѿ����˺�׺���Ͳ�����
        
    current_period = ContextInfo.period 
    
    # ... ��������д��뱣�ֲ��䣬����ʹ�ò�ȫ��� stock ���� ...
    # ��ȫ���������Ҳ����ѡ������ڣ�����ͨ������ '1d'��
    current_period = ContextInfo.period 
    
    if ContextInfo.bar_idx % 200 == 0:
        print(f"? ����: ���ڶ�ȡ�� {ContextInfo.bar_idx} �� K �� (����: {current_period})...")
        
    # �ȴ�ǰ�ڵ� K �߻��ۣ����� 130 ����������
    if ContextInfo.bar_idx < ContextInfo.train_len + 30:
        if ContextInfo.is_last_bar():
            print(f"? [���ش���] ͼ���ܹ�ֻ�� {ContextInfo.bar_idx} ��K�ߣ�")
            print(f"   ԭ��ģ����Ҫ���� {ContextInfo.train_len + 30} �����߲���������")
            print(f"   ���������Ҳ�ġ��ز⿪ʼʱ�䡿���� 2020 �꣬����ͼ���ϰ����¼�ͷ��СK�ߣ�")
        return
        
    # ==========================================
    # ѵ��ģ��ģ��
    # ==========================================
    if ContextInfo.bar_idx % ContextInfo.rebalance_freq == 0 or not ContextInfo.is_trained:
        lookback = ContextInfo.train_len + 50 
        
        # ���Դӱ��ػ�ȡ����
        df = ContextInfo.get_market_data_ex(
            fields=['open', 'high', 'low', 'close'], 
            stock_code=[stock],  
            period=current_period, 
            count=lookback
        )[stock]
        
        # �����쳣����
        if df.empty or len(df) < ContextInfo.train_len:
            if ContextInfo.is_last_bar():
                print(f"? [���ݶϲ�] ���Ի�ȡ {lookback} �� {current_period} ���ݣ����ײ�ֻ������ {len(df)} ����")
            return
            
        df['RSI'] = talib.RSI(df['close'].values, timeperiod=14)
        df['MOM'] = talib.MOM(df['close'].values, timeperiod=10)
        df['WILLR'] = talib.WILLR(df['high'].values, df['low'].values, df['close'].values, timeperiod=14)
        df['target'] = np.where(df['close'].shift(-ContextInfo.predict_lag) > df['close'], 1, 0)
        
        train_df = df.dropna().tail(ContextInfo.train_len)
        
        if len(train_df) > 50:
            features = ['RSI', 'MOM', 'WILLR']
            X_train = train_df[features]
            y_train = train_df['target']
            ContextInfo.clf.fit(X_train, y_train)
            ContextInfo.is_trained = True
                
    # ==========================================
    # Ԥ���벥��ģ��
    # ==========================================
    if ContextInfo.is_trained:
        recent_df = ContextInfo.get_market_data_ex(
            fields=['open', 'high', 'low', 'close'], 
            stock_code=[stock], 
            period=current_period, 
            count=30
        )[stock]
        
        if recent_df.empty: return
        
        recent_df['RSI'] = talib.RSI(recent_df['close'].values, timeperiod=14)
        recent_df['MOM'] = talib.MOM(recent_df['close'].values, timeperiod=10)
        recent_df['WILLR'] = talib.WILLR(recent_df['high'].values, recent_df['low'].values, recent_df['close'].values, timeperiod=14)
        
        latest_features = recent_df['RSI'].iloc[-1], recent_df['MOM'].iloc[-1], recent_df['WILLR'].iloc[-1]
        if not np.isnan(latest_features).any():
            X_pred = np.array([latest_features])
            # ��ȡ����(0)�Ϳ���(1)�ľ�����ʣ����� [0.3, 0.7]
            prob_array = ContextInfo.clf.predict_proba(X_pred)[0]
            bull_prob = prob_array[1] # ��ȡ���ǵĸ���
            
            # �Զ�����ֵ��ֻ�п��Ǹ��ʴ��� 0.65 (65%) ʱ����� 1
            if bull_prob > 0.65:
                pred_signal = 1
            else:
                pred_signal = 0
            # ==========================================
            # ? ��ʵ�˻��ֲֲ�ѯģ��
            # ==========================================
            # ?? ע�⣺���������Ž�Ͷ�����������Ͻǵ��ʽ��˺� (�ַ�����ʽ)
            account_id = "34165036"  
            
            # Ĭ����Ϊδ�ֲ�
            holding = False 
            
            # ȥȯ�̷�������ȡ���˻���ǰ�����й�Ʊ�ֲ���ϸ
            position_list = get_trade_detail_data(account_id, "stock", "position")
            
            # �����ֲ��б�����������Ҫ�����Ĺ�Ʊ(stock)��û�������棬�ҳֹ����� > 0
            if position_list:
                for pos in position_list:
                    if pos.m_strInstrumentID == stock and pos.m_nVolume > 0:
                        holding = True
                        break  # �ҵ��˾���������ѭ��
            
            current_price = recent_df['close'].iloc[-1]
            
            # ֻ�е��������µ�һ�죨���һ��K�ߣ�����������վ��ߺ��µ�
            if ContextInfo.is_last_bar():
                print(f"\n=============================================")
                print(f"?? ������ϣ����: {stock} | ����: {current_period}")
                print(f"?? ģ�����: {pred_signal} (1����, 0����) | �۸�: {current_price}")
                print(f"?? �˻���ʵ�ֲ�״̬: {'�ѳֲ�' if holding else 'δ�ֲ�'}")
                
                if pred_signal == 1 and not holding:
                    print(f"?? [ʵ�̶���] ���࣡���������źţ�")
                    passorder(23, 1101,34165036, stock, 5, -1, 100, ContextInfo)
                    
                elif pred_signal == 0 and holding:
                    print(f"??? [ʵ�̶���] ���գ�����ƽ���źţ�")
                    passorder(24, 1101,34165036, stock, 5, -1, 100, ContextInfo)
                    
                elif pred_signal == 1 and holding:
                    print(f"? [ʵ�̶���] ά�ֶ�ͷ�������ֲ֡�")
                    
                elif pred_signal == 0 and not holding:
                    print(f"?? [ʵ�̶���] ά�ֿղ֣�����������")
                print(f"=============================================\n")




