import string
import os
import csv
import pickle
import json
import numpy as np
import pandas as pd
import mentor
from nltk.tokenize import RegexpTokenizer
from nltk import pos_tag
from nltk.stem import PorterStemmer
from keras.models import Sequential
from keras.layers import LSTM, Activation, Dense
from keras.preprocessing.sequence import pad_sequences

'''
This class contains the methods that operate on the questions to normalize them. The questions are tokenized, punctuations are
removed and words are stemmed to bring them to a common platform
'''
class NLTKPreprocessor(object):
    def __init__(self):
        self.punct = set(string.punctuation)
        self.stemmer=PorterStemmer()

    def inverse_transform(self, X):
        return [" ".join(doc) for doc in X]

    def transform(self, X):
        return list(self.tokenize(X))

    '''
    Tokenizes the input question. It also performs case-folding and stems each word in the question using Porter's Stemmer.
    '''
    def tokenize(self, sentence):
        tokenizer=RegexpTokenizer(r'\w+')
        # Break the sentence into part of speech tagged tokens
        tokenized_words=[]
        for token, tag in pos_tag(tokenizer.tokenize(sentence)):
            token = token.lower()
            token = token.strip()

            # If punctuation, ignore token and continue
            if all(char in self.punct for char in token):
                continue

            # Stem the token and yield
            try:
                stemmed_token=self.stemmer.stem(token)
            except:
                print("Unicode error. File encoding was changed when you opened it in Excel. ", end=" ")
                print("This is most probably an error due to csv file from Google docs being opened in Word. ", end=" ")
                print("Download the file from Google Docs and DO NOT open it in Excel. Run the program immediately. ", end=" ")
                print("If you want to edit using Excel and then follow instructions at: ")
                print("http://stackoverflow.com/questions/6002256/is-it-possible-to-force-excel-recognize-utf-8-csv-files-automatically")
                continue

            yield stemmed_token

class ClassifierPreProcess(object):
    def __init__(self):
        self.train_vectors=[]
        self.test_vectors=[]
        self.lstm_train_vectors=[]
        self.lstm_test_vectors=[]
        self.lstm_train_data=[]
        self.lstm_test_data=[]
        self.last_id=0
        self.w2v_model=None
        self.topic_model=None
        self.topic_set=set()
        self.mentor=None
        self.preprocessor=NLTKPreprocessor()

    def set_mentor(self, mentor):
        self.mentor=mentor

    '''
    get the word_vector and lstm_vector for a question. Both vectors are obtained from the Google News Corpus.
    The difference between these two vectors is given below:
    Question: "What is your name?"
    word_vector: Sum of the w2v representation for each word. Dimension: 300 x 1
    lstm_vector: List of the w2v representation for each word. Dimension: 300 x number_of_words_in_question
    '''
    def get_w2v(self, question):
        current_vector=np.zeros(300,dtype='float32')
        lstm_vector=[]
        for word in question:
            try:
                word_vector=self.w2v_model[word]
            except:
                word_vector=np.zeros(300,dtype='float32')
            lstm_vector.append(word_vector)
            current_vector+=word_vector
        return current_vector, lstm_vector

    '''
    Generate the training question vectors. For the Topic LSTM, each word should be represented by its own 300-length vector.
    For the classifier, the word vectors are added to form a single vector.
    '''
    def generate_training_vectors(self):
        train_data = self.mentor.load_training_data()
        #for each data point, get w2v vector for the question and store in train_vectors.
        #instance=<question, topic, answer, paraphrases>
        for instance in train_data:
            w2v_vector, lstm_vector=self.get_w2v(instance[1])
            self.train_vectors.append([instance[0],w2v_vector.tolist(),instance[2],instance[3]])
            self.lstm_train_vectors.append(lstm_vector)

        test_data = self.mentor.load_testing_data()
        #For the LSTM, each training sample will have a max dimension of 300 x 25. For those that don't, the pad_sequences
        #function will pad sequences of [0, 0, 0, 0....] vectors to the end of each sample.
        padded_vectors=pad_sequences(self.lstm_train_vectors,maxlen=25, dtype='float32',padding='post',truncating='post',value=0.)
        self.lstm_train_vectors=padded_vectors
        #The test set might not be present when just training the dataset fully and then letting users ask questions.
        #That's why the test set code is inside a try-except block.
        try:
            for instance in test_data:
                w2v_vector, lstm_vector=self.get_w2v(instance[1])
                self.test_vectors.append([instance[0],w2v_vector.tolist(),instance[2],instance[3]])
                self.lstm_test_vectors.append(lstm_vector)
            padded_vectors=pad_sequences(self.lstm_test_vectors,maxlen=25, dtype='float32',padding='post',truncating='post',value=0.)
            self.lstm_test_vectors=padded_vectors
        except:
            pass

    '''
    For each question, the sparse topc vectors are created. If a question belongs to topic JobSpecific and Travel, then, a vector
    of size 40 (number of topics) is created with the vector having 1 for JobSpecific and Travel, and 0 for all other topics.
    This is done for both train and test sets.
    '''
    def generate_sparse_topic_vectors(self):
        #Generate the sparse topic train_vectors
        for i in range(len(self.train_vectors)):
            question=self.train_vectors[i][0]
            vector=self.train_vectors[i][1]
            current_topics=self.train_vectors[i][2]
            topic_vector=[0]*len(self.mentor.topics)
            for j in range(len(self.mentor.topics)):
                if self.mentor.topics[j] in current_topics:
                    topic_vector[j]=1
            self.train_vectors[i][2]=topic_vector
            self.lstm_train_data.append([question,self.lstm_train_vectors[i].tolist(),topic_vector])
        #The test set might not be present when just training the dataset fully and then letting users ask questions.
        #That's why the test set code is inside a try-except block.
        try:
            #Generate the sparse topic test_vectors
            for i in range(len(self.test_vectors)):
                question=self.test_vectors[i][0]
                vector=self.test_vectors[i][1]
                current_topics=self.test_vectors[i][2]
                topic_vector=[0]*len(self.mentor.topics)
                for j in range(len(self.mentor.topics)):
                    if self.mentor.topics[j] in current_topics:
                        topic_vector[j]=1
                self.test_vectors[i][2]=topic_vector
                self.lstm_test_data.append([question,self.lstm_test_vectors[i].tolist(),topic_vector])
        except:
            pass


    '''
    Write the train and test data to json (.json) files that can be unpickled in lstm.py and classify.py. This is just dumping
    the data into a file and then undumping it
    '''
    def write_data(self):
        if not os.path.exists("train_data"):
            os.mkdir("train_data")
        if not os.path.exists("test_data"):
            os.mkdir("test_data")

        #dump lstm_train_data
        with open(os.path.join("mentors",self.mentor.id,"train_data","lstm_train_data.json"),'w') as json_file:
            json.dump(self.lstm_train_data, json_file)
        #dump train_vectors for logistic regression
        with open(os.path.join("mentors",self.mentor.id,"train_data","lr_train_data.json"),'w') as json_file:
            json.dump(self.train_vectors,json_file)

        #The test set might not be present when just training the dataset fully and then letting users ask questions.
        #That's why the test set code is inside a try-except block.
        try:
            #dump lstm_test_data
            with open(os.path.join("mentors",self.mentor.id,"test_data","lstm_test_data.json"),'w') as json_file:
                json.dump(self.lstm_test_data, json_file)
            #dump test_vectors for logistic regression
            with open(os.path.join("mentors",self.mentor.id,"test_data","lr_test_data.json"),'w') as json_file:
                json.dump(self.test_vectors,json_file)
        except:
            pass
