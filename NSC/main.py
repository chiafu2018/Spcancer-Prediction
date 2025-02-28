import os 
import time
import math
import numpy as np
import pandas as pd
import tensorflow as tf
from sklearn.model_selection import KFold, train_test_split
from sklearn.metrics import roc_auc_score, roc_curve, precision_recall_curve, auc
from tensorflow.keras.models import Sequential
from tensorflow.keras.layers import Dense, Dropout, BatchNormalization
from tensorflow.keras.optimizers import Adam
from tensorflow.keras.callbacks import ReduceLROnPlateau
from tensorflow.keras.utils import to_categorical
import utils

os.environ['CUDA_VISIBLE_DEVICES'] = '-1'

from abc import ABC, abstractmethod

# Base classifier class
class Classifier(ABC):
    @abstractmethod
    def fit(self, X, y):
        pass

    @abstractmethod
    def predict(self, X):
        pass

# Implement the seesawing weights algorithm 
class SeeSawingWeights(Classifier):
    def __init__(self, epoch, auc_global, auc_local):
        self.model = None
        self.epoch = epoch
        self.ser_weight = 0.0
        self.loc_weight = 0.0
        self.auc_global = auc_global
        self.auc_local = auc_local
        self.convergence_number = 20
        self.loss = []
        
    def fit(self, X, y, institution, seed):
        start_time = time.time()
        lr = 1/len(X)
        self.ser_weight = self.auc_global / (self.auc_global + self.auc_local)
        self.loc_weight = self.auc_local / (self.auc_global + self.auc_local)
        self.loss = []

        for cur in range(self.epoch):
            loss = 0
            # LAEARNING RATE SCHEDULER
            lr *= math.exp(-cur/self.convergence_number)
            test_array = []

            for index, row in X.iterrows():
                yes_prob = self.ser_weight*row.iloc[0] + self.loc_weight*row.iloc[2]
                no_prob = self.ser_weight*row.iloc[1] + self.loc_weight*row.iloc[3]

                if (yes_prob >= no_prob and y[index] == 0):
                    predict_correct = False
                    loss+=yes_prob
                elif (yes_prob < no_prob and y[index] == 1):
                    predict_correct = False
                    loss+=no_prob      
                elif (yes_prob >= no_prob and y[index] == 1):
                    predict_correct = True
                    loss+=no_prob
                elif (yes_prob < no_prob and y[index] == 0):
                    predict_correct = True
                    loss+=yes_prob

                if (not predict_correct):
                    cg = row.iloc[0] if y[index] == 1 else row.iloc[1]
                    cl = row.iloc[2] if y[index] == 1 else row.iloc[3]
                    epsilon_global = math.ceil(max(row.iloc[0], row.iloc[1]) - cg)
                    epsilon_local = math.ceil(max(row.iloc[2], row.iloc[3]) - cl)
                    epsilon = epsilon_global*(1-epsilon_local) + epsilon_local*(1-epsilon_global)
                    delta_weights = lr * ((1-epsilon)*math.exp(abs(cl-cg)/2) + epsilon*math.exp(abs(cl+cg)/2))
                    test_array.append(delta_weights)
                    if epsilon_global == 0 and epsilon_local == 0:
                        if cl > cg:
                            self.ser_weight -= delta_weights
                            self.loc_weight += delta_weights
                        else:
                            self.ser_weight += delta_weights
                            self.loc_weight -= delta_weights
                    elif epsilon_global == 1 and epsilon_local == 1:
                        if cl < cg:
                            self.ser_weight -= delta_weights
                            self.loc_weight += delta_weights
                        else:
                            self.ser_weight += delta_weights
                            self.loc_weight -= delta_weights
                    elif epsilon_global == 0 and epsilon_local == 1:
                        self.ser_weight += delta_weights
                        self.loc_weight -= delta_weights
                    elif epsilon_global == 1 and epsilon_local == 0:
                        self.ser_weight -= delta_weights
                        self.loc_weight += delta_weights

            self.loss.append(loss)

        print("New server weights:", self.ser_weight)
        print("New local weights:", self.loc_weight)

        end_time = time.time()
        execution_time = end_time - start_time

        # utils.draw_loss_function(history=(np.arange(self.epoch), self.loss), name = 'seesawing weights')
        utils.featureInterpreter_SSW(self.ser_weight, self.loc_weight, institution, seed)

        return execution_time

    def predict(self, X, y_test):
        y = []
        pred_prob = []
        for index, row in X.iterrows():
            yes_prob = self.ser_weight * row.iloc[0] + self.loc_weight * row.iloc[2]
            pred_prob.append(yes_prob)

        fpr, tpr, threshold = roc_curve(y_test, pred_prob)
        optimal_index = np.argmax(tpr - fpr)
        y = [1 if prob >= threshold[optimal_index] else 0 for prob in pred_prob]

        return y

    def predict_proba(self, X):
        prob = []
        for index, row in X.iterrows():
            yes_prob = self.ser_weight*row.iloc[0]+self.loc_weight*row.iloc[2]
            no_prob = self.ser_weight*row.iloc[1]+self.loc_weight*row.iloc[3]
            prob.append(np.array(yes_prob , no_prob))

        prob = np.array(prob)
        return prob
    


class DualPerceptionNet(Classifier):
    def __init__(self, epoch, learning_rate):
        self.epoch = epoch
        self.learning_rate = learning_rate
        self.model = Sequential()
        self.model.add(Dense(8, activation='relu', input_shape=(4,)))
        self.model.add(BatchNormalization())
        self.model.add(Dropout(0.1))
        self.model.add(Dense(4, activation='relu'))
        self.model.add(BatchNormalization())
        self.model.add(Dense(2, activation='softmax'))
        self.model.compile(optimizer=Adam(learning_rate=self.learning_rate), loss="categorical_crossentropy", metrics=['accuracy'])


    def fit(self, X, y, institution, seed):
        start_time = time.time()

        beta = (len(X)-1)/len(X)
        class_weights = utils.get_class_balanced_weights(y, beta)
        lr_scheduler = ReduceLROnPlateau(monitor='loss', factor=0.5, patience=5, min_lr=0.0000005)
        history = self.model.fit(X, to_categorical(y, num_classes=2), epochs=self.epoch, class_weight=class_weights, callbacks=[lr_scheduler])

        end_time = time.time()
        execution_time = end_time - start_time    

        # utils.draw_loss_function(history=history, name='NN network')
        utils.featureInterpreter('DPN', self.model, X.astype(float), institution, 'nsc' , seed)

        return execution_time

    def predict(self, X, y_test):
        pred_prob = self.model.predict(X)
        y = [1 if prob[1] >= prob[0] else 0 for prob in pred_prob]
        return y

    def predict_proba(self, X):
        prob = self.model.predict(X)
        return prob[:,1]


def evaluate_model(model, X_test, y_test, training_time):
    predictions = model.predict(X_test, y_test)
    proba = model.predict_proba(X_test)

    if np.sum(y_test):
        auroc = roc_auc_score(y_test, proba)
        precision, recall, _ = precision_recall_curve(y_test, proba)
        auprc = auc(recall, precision)
    else:
        auroc, auprc = None, None

    return {
        'auroc': auroc,
        'auprc': auprc,
        'training time': training_time
    }


def main():
    '''
    If you use the script to run this program, where you can test multiple seeds per time. You need to comment 
    LINE: institution, seed = int(input("Please choose a hospital: 1 for Taiwan, 2 for US (SEER Database): ")), 42
    Otherwise, you need to comment the following line, where you can only test for one seed.
    LINE: institution, seed = utils.parse_argument_for_running_script()
    '''
    institution, seed = utils.parse_argument_for_running_script()
    # institution, seed = int(input("Please choose a hospital: 1 for Taiwan, 2 for US (SEER Database): ")), 42
    
    df = pd.read_csv(f'middle_{institution}.csv')

    trainset, testset = train_test_split(df, test_size=0.33, stratify=df['Outcome'], random_state=seed)

    x_train, y_train = trainset.drop(columns=['Outcome']), trainset['Outcome']
    x_test, y_test = testset.drop(columns=['Outcome']), testset['Outcome']

    df_init = pd.read_csv(f'init_{institution}.csv')
    auc_global = df_init['global auroc'].iloc[0]
    auc_local = df_init['local auroc'].iloc[0]

    models = {
        'SSW': SeeSawingWeights(epoch = 30, auc_global = auc_global, auc_local = auc_local),
        'DPN': DualPerceptionNet(epoch = 300, learning_rate = 0.003)
    }

    all_results = []

    for name, model in models.items():
        training_time = model.fit(x_train, y_train, institution, seed)
        result = evaluate_model(model, x_test, y_test, training_time)
        result['model'] = name
        all_results.append(result)

    # Saving NSC Models Results 
    hospital = 'Taiwan' if institution == 1 else 'USA'
    all_results = pd.DataFrame(all_results)
    all_results = all_results[['model', 'auroc', 'auprc', 'training time']]
    all_results.rename(columns={'model': f'Model | {hospital} | seed={seed}'}, inplace=True)
    all_results.to_csv('Results/Results_NSC.csv', mode='a', index=False)
    print("results saved to Results_NSC.csv")

if __name__ == "__main__":
    main()
